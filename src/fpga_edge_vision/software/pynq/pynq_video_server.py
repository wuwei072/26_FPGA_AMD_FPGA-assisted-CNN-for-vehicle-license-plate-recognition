"""PYNQ摄像头/双DMA服务8080传视频，8081传命令和状态"""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import queue
import socket
import threading
import time
import urllib.request

import cv2
import numpy as np

from video_protocol import VIDEO_PORT, CONTROL_PORT, pack_frame

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 640, 480


def valid_roi(fields):
    x, y, w, h = map(int, fields[:4])
    return w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= WIDTH and y + h <= HEIGHT


def save_roi(frame, fields, folder, automatic=False):
    x, y, w, h = map(int, fields[:4])
    prefix = "auto_roi" if automatic else "roi"
    path = folder / (prefix + datetime.now().strftime("_%Y%m%d_%H%M%S_%f.jpg"))
    if not cv2.imwrite(str(path), frame[y:y + h, x:x + w]):
        raise OSError("ROI图片保存失败")
    return path


def encode_images(frame, edge):
    # 保留真实二值图；框和画中画由电脑绘制
    if cv2.countNonZero(cv2.inRange(edge, 1, 254)):
        raise ValueError("FPGA边缘图包含0/255以外的值")
    png_options = [cv2.IMWRITE_PNG_COMPRESSION, 1]
    if hasattr(cv2, "IMWRITE_PNG_BILEVEL"):
        png_options += [cv2.IMWRITE_PNG_BILEVEL, 1]
    ok_color, color = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    ok_edge, binary = cv2.imencode(".png", edge, png_options)
    if not ok_color or not ok_edge:
        raise RuntimeError("图像编码失败")
    return color.tobytes(), binary.tobytes()


class AsyncPlateSender:
    def __init__(self, url):
        self.url = url
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.busy = self.closed = False
        self.message, self.kind = "[AI 识别] 等待抓拍", "idle"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def send_async(self, path):
        with self.lock:
            if self.busy or self.closed:
                return False
            self.busy = True
            self.message, self.kind = "[AI 识别] 请求发送中...", "pending"
        self.pool.submit(self._send, path)
        return True

    def _send(self, path):
        message, kind = "[AI 识别] 识别失败/超时", "error"
        try:
            request = urllib.request.Request(self.url, data=path.read_bytes(),
                                             headers={"Content-Type": "image/jpeg"}, method="POST")
            with self.opener.open(request, timeout=3.0) as response:
                result = json.loads(response.read().decode("utf-8"))
            if result.get("status") == "success" and result.get("plate"):
                message = f'[AI 识别] {result["plate"]} (耗时 {float(result["time_ms"]):.0f}ms)'
                kind = "saved"
        except Exception:
            pass  # 网络失败只更新识别状态，视频继续运行
        finally:
            with self.lock:
                self.message, self.kind, self.busy = message, kind, False

    def status(self):
        with self.lock:
            return self.message, self.kind

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False)


class AutoCapture:
    def __init__(self):
        self.enabled = False
        self.cooldown_until = 0.0
        self.reset()
        self.message, self.kind = "[自动抓拍未开启]", "idle"

    def reset(self):
        self.since = self.reference = self.last_frame_at = None

    def toggle(self, enabled):
        self.enabled = enabled
        self.cooldown_until = 0.0
        self.reset()
        self.message = "等待目标" if enabled else "[自动抓拍未开启]"
        self.kind = "idle"

    def ready(self, fields):
        now = time.monotonic()
        if not self.enabled:
            return False
        if now < self.cooldown_until:
            self.reset()
            self.message, self.kind = f"[冷却中] 剩余 {self.cooldown_until - now:.1f} 秒", "pending"
            return False
        if not valid_roi(fields):
            self.reset()
            self.message, self.kind = "等待目标", "idle"
            return False
        roi = tuple(map(int, fields[:4]))
        if (self.reference is None or now - self.last_frame_at > 0.5
                or self.iou(roi, self.reference) < 0.6):
            self.reference, self.since = roi, now
        self.last_frame_at = now
        elapsed = now - self.since
        self.message, self.kind = f"[稳定检测中] {elapsed:.1f} / 1.0 秒", "pending"
        return elapsed >= 1.0

    @staticmethod
    def iou(first, second):
        x, y, w, h = first
        a, b, c, d = second
        overlap = max(0, min(x + w, a + c) - max(x, a)) * max(0, min(y + h, b + d) - max(y, b))
        return overlap / (w * h + c * d - overlap)

    def saved(self, path):
        self.reset()
        self.cooldown_until = time.monotonic() + 4.0
        self.message, self.kind = "[已抓拍] " + path.name, "saved"


class ControlLink:
    """接收线程只登记命令；摄像头、DMA和写盘由主循环执行"""
    def __init__(self, connection):
        self.socket = connection
        self.commands = queue.Queue()
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._receive, daemon=True)
        self.thread.start()

    def _receive(self):
        pending = b""
        try:
            while not self.closed.is_set():
                try:
                    data = self.socket.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    self.commands.put(json.loads(line.decode("utf-8"))["command"])
        except (OSError, ValueError, KeyError):
            pass
        finally:
            self.closed.set()

    def send(self, data):
        payload = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.socket.sendall(payload)
        except OSError as exc:
            raise ConnectionError("控制连接已断开") from exc

    def close(self):
        self.closed.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        self.thread.join(timeout=1.0)


def serve_client(video, control, camera, runtime, ai_url, save_dir):
    link = ControlLink(control)
    ai = AsyncPlateSender(ai_url)
    automatic = AutoCapture()
    durations = deque(maxlen=60)
    capture_pending = False
    capture_msg, capture_kind = "[就绪]", "idle"
    benchmark = None
    frame_id = 0
    try:
        while not link.closed.is_set():
            benchmark_pending = False
            while True:
                try:
                    command = link.commands.get_nowait()
                except queue.Empty:
                    break
                if command == "CAPTURE":
                    capture_pending = True
                    capture_msg, capture_kind = "[待抓拍] 等待有效ROI", "pending"
                elif command == "BENCHMARK":
                    benchmark_pending = True
                elif command in ("AUTO_ON", "AUTO_OFF"):
                    automatic.toggle(command == "AUTO_ON")

            ok, frame = camera.read()
            if not ok or frame is None:
                raise RuntimeError("USB摄像头读取失败")
            if frame.shape != (HEIGHT, WIDTH, 3) or frame.dtype != np.uint8:
                raise ValueError("摄像头需要输出原生640x480 BGR图像")
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_id = (frame_id + 1) & 0xFFFFFFFF
            if benchmark_pending:
                # 同一张gray先跑ARM，再跑FPGA；参考算法只在按钮触发时运行
                from opencv_benchmark import opencv_roi_pipeline, result_fields
                automatic.reset()
                started = time.perf_counter()
                arm_fields = result_fields(opencv_roi_pipeline(gray))
                arm_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            fields, edge, dma_ms = runtime.run_gray(gray)
            call_ms = (time.perf_counter() - started) * 1000
            fields = list(map(int, fields))
            durations.append(call_ms)
            if benchmark_pending:
                benchmark = dict(frame_id=frame_id, arm_ms=arm_ms, fpga_ms=call_ms,
                                 match=arm_fields == fields)
                automatic.reset()  # 冻结测试帧不累计自动抓拍稳定时间

            if capture_pending and valid_roi(fields):
                capture_pending = False
                try:
                    path = save_roi(frame, fields, save_dir)
                    capture_msg, capture_kind = "[已保存] " + path.name, "saved"
                    ai.send_async(path)
                except OSError as exc:
                    capture_msg, capture_kind = str(exc), "error"
            if not benchmark_pending and automatic.ready(fields):
                automatic.reset()
                try:
                    path = save_roi(frame, fields, save_dir, automatic=True)
                    automatic.saved(path)
                    ai.send_async(path)
                except OSError as exc:
                    automatic.message, automatic.kind = str(exc), "error"

            color_data, edge_data = encode_images(frame, edge)
            ai_msg, ai_kind = ai.status()
            link.send(dict(type="status", frame_id=frame_id, fields=fields,
                           fpga_call_ms=call_ms, average_ms=sum(durations) / len(durations),
                           capture_msg=capture_msg, capture_kind=capture_kind,
                           auto_enabled=automatic.enabled, auto_msg=automatic.message,
                           auto_kind=automatic.kind, ai_msg=ai_msg, ai_kind=ai_kind,
                           benchmark=benchmark))
            try:
                video.sendall(pack_frame(frame_id, fields[:4], dma_ms, color_data, edge_data))
            except OSError as exc:
                raise ConnectionError("视频连接已断开") from exc
    finally:
        link.close()
        ai.close()


def listen(port):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", port))
    listener.listen(1)
    return listener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-ip", default="192.168.2.1", help="运行Flask识别服务的电脑IP")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--save-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    args.save_dir.mkdir(parents=True, exist_ok=True)
    from edge_dma_runtime import EdgeDmaRuntime
    runtime = camera = None
    try:
        with listen(VIDEO_PORT) as video_listener, listen(CONTROL_PORT) as control_listener:
            runtime = EdgeDmaRuntime(ROOT, timeout_s=3.0)
            camera = cv2.VideoCapture(args.camera)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not camera.isOpened():
                raise RuntimeError("无法打开USB摄像头")
            control_listener.settimeout(5.0)
            print(f"视频端口 {VIDEO_PORT}，控制端口 {CONTROL_PORT}；等待电脑连接", flush=True)
            while True:
                video, address = video_listener.accept()
                with video:
                    try:
                        control, _ = control_listener.accept()
                    except socket.timeout:
                        print("控制连接未建立，请在电脑重新连接", flush=True)
                        continue
                    video.settimeout(3.0)
                    control.settimeout(3.0)
                    video.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    control.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    print("客户端已连接:", address[0], flush=True)
                    try:
                        serve_client(video, control, camera, runtime,
                                     f"http://{args.pc_ip}:5000/api/recognize", args.save_dir)
                    except ConnectionError:
                        print("客户端已断开，等待重新连接", flush=True)
    except KeyboardInterrupt:
        print("服务已停止")
    except TimeoutError:
        print("DMA超时，请重启板子后重新运行")
        return 1
    finally:
        if camera is not None:
            camera.release()
        if runtime is not None:
            runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
