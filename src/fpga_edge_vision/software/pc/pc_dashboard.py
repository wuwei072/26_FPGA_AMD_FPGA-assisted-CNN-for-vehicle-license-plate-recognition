"""电脑端双画面窗口：python pc_dashboard.py --host PYNQ的IP"""
import argparse
from collections import OrderedDict
import json
from queue import Empty, Queue
import select
import socket
import sys
import threading
import time

from PyQt5.QtCore import Qt, QByteArray, QRectF, QSize, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (QApplication, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from PyQt5.QtSvg import QSvgRenderer

from video_protocol import recv_frame


# 内嵌SVG画成按钮图标
def toolbar_icon(name, color):
    shapes = {
        "connect": '<circle cx="9" cy="9" r="6.5"/><ellipse cx="9" cy="9" rx="3" ry="6.5"/><path d="M2.5 9h13"/>',
        "capture": '<path d="M6 5l1-2h4l1 2"/><rect x="2" y="5" width="14" height="10" rx="2"/><circle cx="9" cy="10" r="3"/>',
        "auto": '<path d="M3 7a6 6 0 0 1 10-3l2 2M15 2v4h-4M15 11a6 6 0 0 1-10 3l-2-2M3 16v-4h4"/>',
        "benchmark": '<path d="M2 2v14h14M5 12V8M9 12V4M13 12V6"/>',
    }
    icon = QIcon()
    for mode, stroke in ((QIcon.Normal, color), (QIcon.Disabled, "#7a858b")):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18">'
               f'<g fill="none" stroke="{stroke}" stroke-width="1.6" stroke-linecap="round" '
               f'stroke-linejoin="round">{shapes[name]}</g></svg>')
        renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
        for size in (16, 32, 48):
            image = QPixmap(size, size)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            icon.addPixmap(image, mode)
    return icon


# 网络线程的用部分：连接、收发通知和停止线程
class SocketWorker(QThread):
    available = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, host, port):
        super().__init__()
        self.host, self.port = host, port
        self.lock = threading.Lock()
        self.sock = None
        self.latest = None
        self.notice_pending = False

    def connect_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        with self.lock:
            self.sock = sock
        sock.connect((self.host, self.port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.isInterruptionRequested():
            raise ConnectionAbortedError("连接已取消")
        return sock

    def publish(self, packet):
        with self.lock:
            self.latest = packet
            notify = not self.notice_pending
            self.notice_pending = True
        if notify:
            self.available.emit()

    def take_latest(self):
        with self.lock:
            packet, self.latest = self.latest, None
            self.notice_pending = False
        return packet

    def stop(self):
        self.requestInterruption()
        with self.lock:
            sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close_socket(self):
        with self.lock:
            sock, self.sock = self.sock, None
        if sock is not None:
            sock.close()


# 视频线程：从8080端口收两张图，解码后给主界面
class VideoThread(SocketWorker):
    def run(self):
        try:
            sock = self.connect_socket()
            sock.settimeout(5.0)
            while not self.isInterruptionRequested():
                packet = recv_frame(sock)
                color = QImage.fromData(packet.pop("color_data"), "JPEG").copy()
                edge = QImage.fromData(packet.pop("edge_data"), "PNG").copy()
                if color.isNull() or edge.isNull():
                    raise ValueError("收到的图片无法解码")
                packet.update(color=color, edge=edge)
                self.publish(packet)
        except (OSError, EOFError, ValueError) as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
        finally:
            self.close_socket()


# 控制线程：从8081端口发按钮指令，接收状态和ARM测试结果
class ControlThread(SocketWorker):
    def __init__(self, host, port=8081):
        super().__init__(host, port)
        self.commands = Queue()
        self.statuses = OrderedDict()

    def publish(self, packet):
        with self.lock:
            if packet.get("type") == "status":
                self.statuses[packet["frame_id"]] = packet
                while len(self.statuses) > 120:
                    self.statuses.popitem(last=False)
            self.latest = packet
            notify = not self.notice_pending
            self.notice_pending = True
        if notify:
            self.available.emit()

    def take_statuses(self):
        with self.lock:
            packet, self.latest = self.latest, None
            statuses = list(self.statuses.values())
            self.statuses.clear()
            self.notice_pending = False
        return packet, statuses

    def send_command(self, command):
        self.commands.put(command)

    def run(self):
        try:
            sock = self.connect_socket()
            pending = b""
            while not self.isInterruptionRequested():
                try:
                    while True:
                        command = self.commands.get_nowait()
                        sock.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
                except Empty:
                    pass
                if not select.select([sock], [], [], 0.05)[0]:
                    continue
                chunk = sock.recv(65536)
                if not chunk:
                    raise EOFError("控制连接已关闭")
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if line:
                        self.publish(json.loads(line.decode("utf-8")))
        except (OSError, EOFError, ValueError) as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
        finally:
            self.close_socket()


# 显示视频，按比例画ROI框，左图还带一个裁剪画中画
class VideoLabel(QLabel):
    def __init__(self, color, show_crop=False):
        super().__init__()
        self.box_color = QColor(color)
        self.show_crop = show_crop
        self.image = QPixmap()
        self.roi = (0, 0, 0, 0)
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_frame(self, image, roi):
        self.image, self.roi = image, roi
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self.image.isNull():
            painter.setPen(QColor("#a8afb7"))
            painter.drawText(self.rect(), Qt.AlignCenter, "等待视频连接")
            return
        width, height = self.image.width(), self.image.height()
        scale = min(self.width() / width, self.height() / height)
        target = QRectF((self.width() - width * scale) / 2,
                        (self.height() - height * scale) / 2, width * scale, height * scale)
        painter.drawPixmap(target, self.image, QRectF(self.image.rect()))
        x, y, w, h = self.roi
        valid = w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= width and y + h <= height
        if not valid:
            return
        painter.setPen(QPen(self.box_color, 2))
        painter.drawRect(QRectF(target.x() + x * scale, target.y() + y * scale,
                               w * scale, h * scale).adjusted(1, 1, -1, -1))
        if self.show_crop:
            crop = self.image.copy(x, y, w, h)
            pw, ph = min(200.0, target.width() * 0.30), min(150.0, target.height() * 0.31)
            box = QRectF(target.right() - pw - 8, target.bottom() - ph - 8, pw, ph)
            painter.fillRect(box.adjusted(0, -20, 0, 0), Qt.black)
            painter.setPen(Qt.white)
            painter.setFont(QFont(self.font().family(), 9))
            painter.drawText(box.adjusted(6, -20, 0, -ph), Qt.AlignVCenter, "ROI CROP")
            ratio = min(pw / w, ph / h)
            crop_rect = QRectF(box.center().x() - w * ratio / 2,
                              box.center().y() - h * ratio / 2, w * ratio, h * ratio)
            painter.drawPixmap(crop_rect, crop, QRectF(crop.rect()))
            painter.drawRect(box)


# 主窗口：摆放控件、绑定按钮，并更新画面和数据
class Dashboard(QMainWindow):
    frames_ready = pyqtSignal(QPixmap, QPixmap, dict)

    def __init__(self, host="192.168.2.99", video_port=8080, control_port=8081):
        super().__init__()
        self.video_port, self.control_port = video_port, control_port
        self.video = self.control = None
        self.workers = []
        self.running = self.closing = False
        self.last_error = ""
        self.current = None
        self.benchmark = None
        self.metadata = OrderedDict()
        self.fps_frames = 0
        self.fps_time = time.perf_counter()
        self.ui_fps = None
        self.setWindowTitle("FPGA Real-Time Edge Vision")
        self.setFont(QFont("Segoe UI", 11))
        self.setMinimumSize(720, 540)
        area = self.screen().availableGeometry()
        self.resize(min(1100, round(area.width() * 0.75)),
                    min(720, round(area.height() * 0.75)))
        self.move(area.center() - self.rect().center())
        root = QWidget()
        root.setObjectName("dashboard")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        self.controls = QGridLayout()
        self.controls.setSpacing(8)
        self.toolbar_mode = None
        self.address = QLineEdit(host)
        self.address.setPlaceholderText("PYNQ IP")
        self.address.setMaximumWidth(145)
        self.address.setMinimumWidth(90)
        self.connect_button = QPushButton("连接 PYNQ")
        self.capture = QPushButton("抓拍当前 ROI")
        self.capture.setObjectName("captureButton")
        self.auto = QPushButton("自动抓拍: 关闭")
        self.auto.setCheckable(True)
        self.arm = QPushButton("运行 ARM 对比")
        self.arm.setObjectName("armButton")
        for button, name, color in ((self.connect_button, "connect", "#68dbe7"),
                                    (self.capture, "capture", "#71ff9a"),
                                    (self.auto, "auto", "#8fc9ff"),
                                    (self.arm, "benchmark", "#ffcf67")):
            button.setIcon(toolbar_icon(name, color))
            button.setIconSize(QSize(16, 16))
        for widget in (self.address, self.connect_button, self.capture, self.auto, self.arm):
            widget.setFixedHeight(30)

        self.control_groups = []
        for name, widgets in (("CONNECTION", (self.address, self.connect_button)),
                              ("CAPTURE", (self.capture, self.auto)),
                              ("BENCHMARK", (self.arm,))):
            group = QGroupBox(name)
            group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            row = QHBoxLayout(group)
            row.setContentsMargins(8, 14, 8, 6)
            row.setSpacing(6)
            for widget in widgets:
                row.addWidget(widget)
            self.control_groups.append(group)

        self.title = QLabel("FPGA Real-Time Edge Vision")
        self.title.setObjectName("mainTitle")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.live = QLabel()
        self.live.setObjectName("liveStatus")
        self.live.setAlignment(Qt.AlignCenter)
        self.live.setWordWrap(False)
        self.live.setFixedHeight(32)
        self.live.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.set_live_status("● OFFLINE", "#ff8181", "#321f24")
        self.live.setToolTip("FPS 为电脑端每秒接收并提交显示帧数")
        self.toolbar_widgets = (*self.control_groups, self.title, self.live)
        self.arrange_controls()
        layout.addLayout(self.controls)

        images = QHBoxLayout()
        images.setSpacing(12)
        self.left, self.right = VideoLabel("#00ff00", True), VideoLabel("#FFCA28")
        for heading_text, image in (("Camera Input + FPGA ROI", self.left),
                                    ("Real FPGA Binary Sobel Edge", self.right)):
            panel = QFrame()
            panel.setObjectName("panel")
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            label = QLabel(heading_text)
            label.setObjectName("videoTitle")
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            column.addWidget(label)
            column.addWidget(image, 1)
            images.addWidget(panel, 1)
        layout.addLayout(images, 1)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        metrics = QVBoxLayout(panel)
        metrics.setContentsMargins(12, 8, 12, 8)
        metrics.setSpacing(2)
        self.lines = []
        for index in range(7):
            label = QLabel("--")
            label.setObjectName("metricLine")
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setStyleSheet("color:%s; font-weight:%s;" %
                               ("#59ff8b" if index == 3 else "#d4d7da",
                                "700" if index in (0, 1, 3) else "400"))
            metrics.addWidget(label)
            self.lines.append(label)
        layout.addWidget(panel)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.capture.clicked.connect(lambda: self.command("CAPTURE"))
        self.arm.clicked.connect(lambda: self.command("BENCHMARK"))
        self.auto.toggled.connect(self.toggle_auto)
        self.frames_ready.connect(self.show_frame)
        self.setStyleSheet("""
            QWidget {font-family:"Segoe UI", "Microsoft YaHei UI", sans-serif; font-size:13px;}
            QWidget#dashboard {background:#151718; color:#e1e4e7;}
            QFrame#panel {background:#222627; border:1px solid #41494d; border-radius:12px;}
            QLabel {border:0; color:#e1e4e7;}
            QLabel#mainTitle {font-size:16px; font-weight:700; color:white; padding:0 12px 0 0;}
            QGroupBox {background:#1b2022; border:1px solid #41494d; border-radius:5px;
                margin-top:7px; font-size:12px; font-weight:600; color:#9aabb4;}
            QGroupBox::title {subcontrol-origin:margin; subcontrol-position:top left;
                left:8px; padding:0 4px;}
            QLabel#videoTitle {font-size:14px; font-weight:700; padding:5px;}
            QLabel#liveStatus {font-size:13px;}
            QLabel#metricLine {font-size:13px;}
            QPushButton,QLineEdit {color:#e1e4e7; background:#303638; border:1px solid #586266;
                border-radius:5px; padding:4px 8px; font-size:13px;}
            QPushButton {font-weight:700;}
            QLineEdit {font-weight:400;}
            QPushButton#captureButton {background:#205b39; border-color:#39865b;}
            QPushButton#armButton {background:#735a19; border-color:#aa8530;}
            QPushButton:hover {border-color:#b5c3c9;}
            QPushButton:checked {background:#205b39; border-color:#39865b;}
            QPushButton:disabled {color:#899294; background:#292d2f; border-color:#41494d;}
        """)
        self.enable_actions(False)
        self.lines[4].setText("[抓拍状态] [就绪]")
        self.lines[5].setText("[自动抓拍] [未开启]")
        self.lines[6].setText("[AI识别] 等待抓拍")
        self.arrange_controls()
        self.fps_timer = QTimer(self)
        self.fps_timer.setInterval(1000)
        self.fps_timer.timeout.connect(self.refresh_fps)


    def arrange_controls(self):
        mode = 0 if self.width() >= 1150 else (1 if self.width() >= 900 else 2)
        if mode == self.toolbar_mode:
            return
        self.toolbar_mode = mode
        for widget in self.toolbar_widgets:
            self.controls.removeWidget(widget)
        for column in range(5):
            self.controls.setColumnStretch(column, 0)
        for column, group in enumerate(self.control_groups):
            self.controls.addWidget(group, 0, column, 2 if mode == 1 else 1, 1)
        if mode == 0:
            self.controls.addWidget(self.title, 0, 3)
            self.controls.addWidget(self.live, 0, 4, Qt.AlignRight)
            self.controls.setColumnStretch(3, 1)
        elif mode == 1:
            self.controls.addWidget(self.live, 0, 3, Qt.AlignRight)
            self.controls.addWidget(self.title, 1, 3)
            self.controls.setColumnStretch(3, 1)
        else:
            self.controls.addWidget(self.title, 1, 0, Qt.AlignLeft)
            self.controls.addWidget(self.live, 1, 1, 1, 2, Qt.AlignRight)
            self.controls.setColumnStretch(2, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toolbar_widgets"):
            self.arrange_controls()

    def set_live_status(self, text, color, background):
        self.live_state = (text, color, background)
        fps = "--" if self.ui_fps is None else f"{self.ui_fps:.1f}"
        self.live.setText(f"{fps} FPS | {text}")
        self.live.setStyleSheet(
            f"color:{color}; background:{background}; border:1px solid {color};"
            "border-radius:15px; padding:0 10px; font-weight:700;")

    # 每秒统计提交给界面的帧数，再按实际经过时间计算FPS
    def refresh_fps(self):
        now = time.perf_counter()
        self.ui_fps = self.fps_frames / (now - self.fps_time)
        self.fps_frames = 0
        self.fps_time = now
        self.set_live_status(*self.live_state)

    def enable_actions(self, enabled):
        for button in (self.capture, self.auto, self.arm):
            button.setEnabled(enabled)

    def toggle_connection(self):
        if self.workers:
            self.disconnect()
            return
        host = self.address.text().strip()
        if not host:
            return
        self.fps_frames = 0
        self.fps_time = time.perf_counter()
        self.ui_fps = None
        self.fps_timer.start()
        self.running, self.last_error = True, ""
        self.current, self.metadata = None, OrderedDict()
        self.benchmark = None
        self.address.setEnabled(False)
        self.connect_button.setText("断开连接")
        self.set_live_status("● CONNECTING", "#ffe873", "#332f1c")
        self.live.setToolTip("FPS 为电脑端每秒接收并提交显示帧数")
        self.video = VideoThread(host, self.video_port)
        self.control = ControlThread(host, self.control_port)
        self.workers = [self.video, self.control]
        self.video.available.connect(self.receive_frame)
        self.control.available.connect(self.receive_status)
        for worker in self.workers:
            worker.failed.connect(self.on_error)
            worker.finished.connect(self.worker_finished)
            worker.start()

    def command(self, command):
        if self.running and self.control is not None:
            self.control.send_command(command)

    def toggle_auto(self, enabled):
        self.auto.setText("自动抓拍: 开启" if enabled else "自动抓拍: 关闭")
        self.command("AUTO_ON" if enabled else "AUTO_OFF")

    def receive_frame(self):
        packet = self.video.take_latest()
        if self.running and packet is not None:
            color, edge = packet.pop("color"), packet.pop("edge")
            self.frames_ready.emit(QPixmap.fromImage(color), QPixmap.fromImage(edge), packet)

    def show_frame(self, color, edge, packet):
        self.fps_frames += 1
        self.current = packet
        self.left.set_frame(color, packet["roi"])
        self.right.set_frame(edge, packet["roi"])
        active = packet["roi"][2] > 0 and packet["roi"][3] > 0
        if active:
            self.set_live_status("● LIVE / ROI ACTIVE", "#59ff8b", "#163222")
        else:
            self.set_live_status("● LIVE / NO ACTIVE ROI", "#ff8181", "#321f24")
        self.enable_actions(True)
        self.update_metrics()

    # 状态按帧号和图像对应，抓拍及AI识别提示也在这更新
    def receive_status(self):
        status, updates = self.control.take_statuses()
        if not self.running or status is None:
            return
        if status.get("type") == "error":
            self.on_error(status.get("message", "板端错误"))
            return
        for update in updates:
            self.metadata[update["frame_id"]] = update
        while len(self.metadata) > 120:
            self.metadata.popitem(last=False)
        self.benchmark = status.get("benchmark")
        for index, key in ((4, "capture"), (5, "auto"), (6, "ai")):
            prefix = {4: "[抓拍状态] ", 5: "[Auto Capture Status] ", 6: ""}[index]
            self.lines[index].setText(prefix + status[key + "_msg"])
            color = {"saved": "#71ff9a", "success": "#71ff9a", "error": "#ff8181",
                     "pending": "#ffe873", "cooldown": "#ffe873"}.get(status[key + "_kind"], "#d4d7da")
            self.lines[index].setStyleSheet("color:%s;" % color)
        self.auto.blockSignals(True)
        self.auto.setChecked(status["auto_enabled"])
        self.auto.blockSignals(False)
        self.auto.setText("自动抓拍: 开启" if status["auto_enabled"] else "自动抓拍: 关闭")
        self.update_metrics()

    # 根据ROI字段更新缩减率、紧凑度和ARM对比数据
    def update_metrics(self):
        if self.current is None:
            return
        packet = self.current
        x, y, w, h = packet["roi"]
        status = self.metadata.get(packet["frame_id"], {})
        fields = status.get("fields")
        grids = str(fields[4]) if fields else "--"
        compact = "%.1f%%" % (100 * fields[4] / ((w / 80) * (h / 80))) if fields and w and h else "--"
        roi = str((x, y, w, h)) if w and h else "NOT DETECTED"
        self.lines[0].setText(f"[ROI RESULT] ROI={roi} | Largest CC Grids: {grids} | Compactness: {compact}")
        area = f"{w*h+12} B | Area Reduction: {100*(1-w*h/307200):.2f}%" if w and h else "NOT DETECTED"
        self.lines[1].setText("[CANDIDATE AREA] Full Gray: 307200 B | Candidate ROI: " + area)
        benchmark = self.benchmark
        arm = f"{benchmark['arm_ms']:.3f}" if benchmark else "--"
        ratio = (f"{benchmark['arm_ms']/benchmark['fpga_ms']:.2f}x"
                 if benchmark and benchmark["match"] and benchmark["fpga_ms"] > 0 else "--x")
        self.lines[2].setText(f"[SOFTWARE REFERENCE] ARM OpenCV: {arm} ms | OpenCV / Call (benchmark frame): {ratio}")
        full = f"{status['fpga_call_ms']:.3f}" if status else "--"
        average = f"{status['average_ms']:.3f}" if status else "--"
        self.lines[3].setText(f"[REAL-TIME PERFORMANCE] FPGA+DMA window: {packet['dma_ms']:.3f} ms | Full call: {full} ms | Call avg (≤60): {average} ms")

    def on_error(self, message):
        self.last_error = message
        self.disconnect()

    def disconnect(self):
        self.fps_timer.stop()
        self.fps_frames = 0
        self.ui_fps = None
        self.running = False
        self.enable_actions(False)
        self.connect_button.setEnabled(False)
        self.set_live_status("● ERROR" if self.last_error else "● OFFLINE", "#ff8181", "#321f24")
        self.live.setToolTip(self.last_error)
        for worker in self.workers:
            worker.stop()

    def worker_finished(self):
        if any(worker.isRunning() for worker in self.workers):
            return
        for worker in self.workers:
            worker.deleteLater()
        self.workers = []
        self.address.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.connect_button.setText("连接 PYNQ")
        self.set_live_status("● ERROR" if self.last_error else "● OFFLINE", "#ff8181", "#321f24")
        self.live.setToolTip(self.last_error)
        if self.closing:
            self.close()

    def closeEvent(self, event):
        if self.workers:
            self.closing = True
            event.ignore()
            self.disconnect()
        else:
            event.accept()


# 创建Qt应用，打开窗口并进入事件循环
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.2.99", help="PYNQ板IPv4地址")
    args = parser.parse_args()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv[:1])
    app.setFont(QFont("Segoe UI", 11))
    window = Dashboard(args.host)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
