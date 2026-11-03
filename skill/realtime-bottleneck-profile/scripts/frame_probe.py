"""短期分段计时：不改业务结果，不累积图像或无限历史。"""
from contextlib import contextmanager
import threading
import time


class FrameProbe:
    def __init__(self, frame_id, mode="demo", clock=time.perf_counter):
        self.frame_id = frame_id
        self.mode = mode
        self.clock = clock
        self.started = clock()
        self.spans = []
        self._lock = threading.Lock()
        self._active = 0
        self._finished = False

    @contextmanager
    def stage(self, name, lane="main"):
        with self._lock:
            if self._finished:
                raise RuntimeError("本帧日志已经结束")
            self._active += 1
        start = self.clock()
        ok = False
        try:
            yield
            ok = True
        finally:
            try:
                self.add_span(name, start, self.clock(), lane, ok)
            finally:
                with self._lock:
                    self._active -= 1

    def add_span(self, name, start, end, lane="main", ok=True):
        # start/end 必须来自同一台主机的同一单调时钟。
        if end < start:
            raise ValueError("阶段结束早于开始")
        with self._lock:
            if self._finished:
                raise RuntimeError("本帧日志已经结束，不能追加后台区间")
            self.spans.append(dict(name=name, start=start, end=end, lane=lane, ok=ok))

    def finish(self):
        with self._lock:
            if self._active:
                raise RuntimeError("仍有计时阶段未结束，不能将其标为完整记录")
            if self._finished:
                raise RuntimeError("本帧日志已经结束")
            self._finished = True
            return dict(schema=1, frame_id=self.frame_id, mode=self.mode,
                        loop_start=self.started, loop_end=self.clock(), spans=list(self.spans))
