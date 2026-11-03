"""双DMA：发送灰度帧，接收ROI字段和FPGA二值边缘图"""
from pathlib import Path
import time
   
import numpy as np
from pynq import Overlay, allocate

WIDTH = 640
HEIGHT = 480
FRAME_BYTES = WIDTH * HEIGHT
ROI_WORDS = 6

# 故障时保留物理缓冲
_RETAINED_RUNTIMES = []

class EdgeDmaRuntime:
    def __init__(self, root, bit_name="sobel_edge.bit", timeout_s=3.0):
        # 如果上次运行DMA死锁则重启板子
        if _RETAINED_RUNTIMES:
            raise RuntimeError("上次DMA未确认结束，请重启板子后运行")

        self.root = Path(root)
        self.timeout_s = float(timeout_s)
        self._safe_to_free = True
        bit_path = self.root / bit_name
        print("加载Overlay:", bit_path)
        
        self.overlay = Overlay(str(bit_path))
        self.dma_roi = self.overlay.axi_dma_0
        self.dma_edge = self.overlay.axi_dma_edge
        self._channels = (self.dma_roi.sendchannel,
                          self.dma_roi.recvchannel,
                          self.dma_edge.recvchannel)

        # 分配三块物理缓存，后续逐帧复用
        self.in_buf = allocate(shape=(FRAME_BYTES,), dtype=np.uint8)    # 输入：640x480灰度图
        self.roi_buf = allocate(shape=(ROI_WORDS,), dtype=np.uint16)    # 输出1：6个16位坐标字段
        self.edge_buf = allocate(shape=(FRAME_BYTES,), dtype=np.uint8)  # 输出2：640x480边缘图
        print("双DMA已就绪")

    def status(self):
        return {
            "main_mm2s_dmasr": int(self.dma_roi.mmio.read(0x04)),
            "main_s2mm_dmasr": int(self.dma_roi.mmio.read(0x34)),
            "edge_s2mm_dmasr": int(self.dma_edge.mmio.read(0x34)),
        }

    def print_status(self, prefix="DMA status"):
        print(prefix)
        for name, value in self.status().items():
            print(f"  {name} = 0x{value:08X}")

    def run_gray(self, gray):
        """返回(ROI六字段, 独立边缘图副本, DMA耗时ms)"""
        if not self._safe_to_free:
            raise RuntimeError("DMA尚未结束，请重启板子后运行")
        if gray.shape != (HEIGHT, WIDTH) or gray.dtype != np.uint8:
            raise ValueError("需要640x480uint8灰度图")

        self.in_buf[:] = gray.reshape(-1)
        started = time.perf_counter()
        self._safe_to_free = False

        # 两路接收先准备好，最后再送入灰度图
        self.dma_roi.recvchannel.transfer(self.roi_buf)
        self.dma_edge.recvchannel.transfer(self.edge_buf)
        self.dma_roi.sendchannel.transfer(self.in_buf)

        deadline = time.monotonic() + self.timeout_s
        while not all(channel.idle for channel in self._channels):
            if time.monotonic() >= deadline:
                self.print_status("DMA超时")
                raise TimeoutError(f"双DMA传输超过{self.timeout_s:.1f}秒")
            time.sleep(0.001)

        for channel in self._channels:
            channel.wait()
        self._safe_to_free = True
        elapsed_ms = (time.perf_counter() - started) * 1000

        roi = self.roi_buf.tolist()
        edge = np.array(self.edge_buf).reshape(HEIGHT, WIDTH)
        return roi, edge, elapsed_ms

    def close(self):
        if not self._safe_to_free:
            if self not in _RETAINED_RUNTIMES:
                _RETAINED_RUNTIMES.append(self)
            print("DMA未确认结束，请重启板子")
            return

        # 物理内存释放
        for buffer in (self.in_buf, self.roi_buf, self.edge_buf):
            if buffer is not None:
                buffer.freebuffer()
        self.in_buf = self.roi_buf = self.edge_buf = None