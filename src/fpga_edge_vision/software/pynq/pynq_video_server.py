"""PYNQ摄像头/双DMA服务。8080传视频，8081传命令和状态"""
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
AUTO_CAPTURE_POLICY = "plate-confirmed-v2"


def valid_roi(fields):
    x, y, w, h = map(int, fields[:4])
    return w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= WIDTH and y + h <= HEIGHT


def save_roi(frame, fields, folder):
    x, y, w, h = map(int, fields[:4])
    path = folder / ("roi" + datetime.now().strftime("_%Y%m%d_%H%M%S_%f.jpg"))
    if not cv2.imwrite(str(path), frame[y:y + h, x:x + w]):
        raise OSError("ROI图片保存失败")
    return path


def encode_images(frame, edge):
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
        self.results = queue.Queue()
        self.busy = self.closed = False
        self.message, self.kind = "[AI 识别] 等待抓拍", "idle"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def send_async(self, path):
        return self._submit(path)

    def send_candidate(self, crop, generation):
        return self._submit(crop, generation)

    def _submit(self, source, generation=None):
        with self.lock:
            if self.busy or self.closed:
                return False
            if generation is not None:
                source = source.copy()
            self.pool.submit(self._send, source, generation)
            self.busy = True
            self.message, self.kind = "[AI 识别] 请求发送中...", "pending"
        return True

    def _send(self, source, generation):
        message, kind = "[AI 识别] 识别服务异常/超时", "error"
        saved_jpeg = None
        try:
            if generation is None:
                jpeg = source.read_bytes()
            else:
                ok, encoded = cv2.imencode(".jpg", source)
                if not ok:
                    raise RuntimeError("ROI编码失败")
                jpeg = encoded.tobytes()
            request = urllib.request.Request(self.url, data=jpeg,
                                             headers={"Content-Type": "image/jpeg"}, method="POST")
            with self.opener.open(request, timeout=3.0) as response:
                result = json.loads(response.read().decode("utf-8"))
            plate = result.get("plate")
            if (result.get("status") == "success" and isinstance(plate, str) and plate.strip()
                    and (generation is None or result.get("auto_save_allowed") is True)):
                elapsed = result.get("time_ms")
                timing = f" (耗时 {float(elapsed):.0f}ms)" if elapsed is not None else ""
                message = f"[AI 识别] {plate.strip()}{timing}"
                kind = "saved"
                saved_jpeg = jpeg
            else:
                message = "[AI 识别] 未识别到车牌"
        except Exception:
            pass  # 网络失败只更新识别状态，视频继续运行
        finally:
            with self.lock:
                self.busy = False
                if not self.closed:
                    self.message, self.kind = message, kind
                    if generation is not None:
                        self.results.put(dict(generation=generation, jpeg=saved_jpeg,
                                              message=message, kind=kind))

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
        self.pending = False
        self.generation = 0
        self.cooldown_until = 0.0
        self.reset()
        self.message, self.kind = "[自动抓拍未开启]", "idle"

    def reset(self):
        self.since = self.reference = self.last_frame_at = None
        self.elapsed = 0.0
        self.bad_frames = 0

    def toggle(self, enabled):
        enabled = bool(enabled)
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self.generation += 1
        self.pending = False
        self.cooldown_until = 0.0
        self.reset()
        self.message = "等待目标" if enabled else "[自动抓拍未开启]"
        self.kind = "idle"

    def ready(self, fields):
        now = time.monotonic()
        if not self.enabled:
            return False
        if self.pending:
            self.message, self.kind = "[处理中]", "pending"
            return False
        if now < self.cooldown_until:
            self.reset()
            self.message, self.kind = f"[冷却中] 剩余 {self.cooldown_until - now:.1f} 秒", "pending"
            return False
        previous = self.last_frame_at
        if previous is not None and now - previous > 1.0:
            self.reset()
            previous = None
        self.last_frame_at = now
        valid = valid_roi(fields)
        roi = tuple(map(int, fields[:4])) if valid else None
        matches = valid and (self.reference is None or self.same_region(roi, self.reference))
        if not matches:
            self.bad_frames += 1
            if self.bad_frames >= 2:
                self.reset()
                self.last_frame_at = now
                if valid:
                    self.reference, self.since = roi, now
            self.message = (f"[稳定检测中] {min(self.elapsed, 1.0):.1f} / 1.0 秒"
                            if self.reference is not None else "等待目标")
            self.kind = "pending" if self.reference is not None else "idle"
            return False
        if self.reference is None:
            self.reference, self.since = roi, now
        elif self.bad_frames == 0 and previous is not None:
            self.elapsed += now - previous
        self.bad_frames = 0
        self.message, self.kind = f"[稳定检测中] {min(self.elapsed, 1.0):.1f} / 1.0 秒", "pending"
        return self.elapsed + 1e-9 >= 1.0

    @staticmethod
    def iou(first, second):
        x, y, w, h = first
        a, b, c, d = second
        overlap = max(0, min(x + w, a + c) - max(x, a)) * max(0, min(y + h, b + d) - max(y, b))
        return overlap / (w * h + c * d - overlap)

    @classmethod
    def same_region(cls, first, second):
        x, y, w, h = first
        a, b, c, d = second
        center_close = abs(2 * x + w - 2 * a - c) <= 80 and abs(2 * y + h - 2 * b - d) <= 80
        size_close = 0.5 <= (w * h) / (c * d) <= 2.0
        return cls.iou(first, second) >= 0.6 or (center_close and size_close)

    def submitted(self):
        self.reset()
        self.pending = True
        self.message, self.kind = "[处理中]", "pending"

    def finish(self, message, kind):
        self.reset()
        self.pending = False
        self.cooldown_until = time.monotonic() + 4.0
        self.message, self.kind = message, kind

    def saved(self, path):
        self.finish("[已抓拍] " + path.name, "saved")


def complete_auto_capture(sender, automatic, folder):
    try:
        result = sender.results.get_nowait()
    except queue.Empty:
        return False
    if not automatic.enabled or result["generation"] != automatic.generation:
        return False
    if result["kind"] != "saved":
        automatic.finish("等待目标", "idle")
        return True
    path = folder / ("auto_roi_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f.jpg"))
    temporary = path.with_suffix(".jpg.tmp")
    try:
        temporary.write_bytes(result["jpeg"])
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        automatic.finish("[保存失败]", "error")
    else:
        automatic.saved(path)
    return True


class ControlLink:
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
                automatic.reset() 

            auto_completed = complete_auto_capture(ai, automatic, save_dir)
            if capture_pending and valid_roi(fields):
                capture_pending = False
                try:
                    path = save_roi(frame, fields, save_dir)
                    capture_msg, capture_kind = "[已保存] " + path.name, "saved"
                    ai.send_async(path)
                except OSError as exc:
                    capture_msg, capture_kind = str(exc), "error"
            if not benchmark_pending and not auto_completed and automatic.ready(fields):
                x, y, w, h = fields[:4]
                if ai.send_candidate(frame[y:y + h, x:x + w], automatic.generation):
                    automatic.submitted()

            color_data, edge_data = encode_images(frame, edge)
            ai_msg, ai_kind = ai.status()
            link.send(dict(type="status", frame_id=frame_id, fields=fields,
                           fpga_call_ms=call_ms, average_ms=sum(durations) / len(durations),
                           capture_msg=capture_msg, capture_kind=capture_kind,
                           auto_capture_policy=AUTO_CAPTURE_POLICY,
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
            print(f"自动抓拍规则: {AUTO_CAPTURE_POLICY}", flush=True)
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
