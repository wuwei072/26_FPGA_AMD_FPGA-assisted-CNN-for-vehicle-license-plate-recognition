"""PYNQ Simple AXI DMA polling transaction; buffers are allocated by the caller."""
from dataclasses import dataclass
import threading
import time


# These offsets belong to AMD AXI DMA Simple mode, not to arbitrary DMA engines.
ERROR_BITS = {0x10: "DMA internal error", 0x20: "DMA slave error",
              0x40: "DMA decode error"}
_QUARANTINED = []


@dataclass
class Endpoint:
    name: str
    channel: object
    buffer: object
    read_status: object
    read_length: object = None

    @property
    def nbytes(self):
        return memoryview(self.buffer).nbytes


def axi_dma_endpoint(dma, direction, buffer, name):
    """Create an adapter for a PYNQ Simple AXI DMA send/receive channel."""
    if direction == "send":
        return Endpoint(name, dma.sendchannel, buffer,
                        lambda: int(dma.mmio.read(0x04)))
    if direction == "recv":
        return Endpoint(name, dma.recvchannel, buffer,
                        lambda: int(dma.mmio.read(0x34)),
                        lambda: int(dma.mmio.read(0x58)))
    raise ValueError("direction must be 'send' or 'recv'")


class DmaTransactionError(RuntimeError):
    def __init__(self, message, status):
        self.status = status
        dump = ", ".join(f"{name}=0x{value:08X}" for name, value in status.items())
        super().__init__(f"{message}; {dump}")


class PollingTransaction:
    """One input, N fixed-length outputs. No implicit allocation, reset, or free.

    Every channel must be exclusively owned by this object. The caller fills the
    input only while run() is not active. run() returns immutable output copies.
    """
    def __init__(self, sender, receivers, timeout_s=3.0, poll_s=0.001):
        self.sender = sender
        self.receivers = tuple(receivers)
        self.endpoints = self.receivers + (sender,)
        if not self.receivers or timeout_s <= 0 or poll_s <= 0:
            raise ValueError("need receivers and positive timeout/poll interval")
        names = [e.name for e in self.endpoints]
        channels = [id(e.channel) for e in self.endpoints]
        if len(set(names)) != len(names) or len(set(channels)) != len(channels):
            raise ValueError("endpoint names and channels must be unique")
        if any(e.nbytes == 0 for e in self.endpoints):
            raise ValueError("zero-length DMA buffer")
        self.timeout_s, self.poll_s = timeout_s, poll_s
        self._lock = threading.Lock()
        self._poisoned = False
        self._in_flight = False
        self._completed_once = False

    @property
    def safe_to_release(self):
        return not self._in_flight

    def status(self):
        return {e.name: int(e.read_status()) for e in self.endpoints}

    def _check_status(self, status):
        for name, value in status.items():
            errors = [label for bit, label in ERROR_BITS.items() if value & bit]
            if errors or value & 1:
                reason = ", ".join(errors) if errors else "channel halted"
                raise DmaTransactionError(f"{name}: {reason}", status)

    def run(self):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("DMA transaction is already running")
        try:
            if self._poisoned:
                raise RuntimeError("transaction faulted; recover hardware before creating a new owner")
            try:
                self._check_status(self.status())
                # A newly started PYNQ channel may be non-idle before its first transfer.
                # After our first completion, all channels must stay idle until reuse.
                if self._completed_once and not all(e.channel.idle for e in self.endpoints):
                    raise DmaTransactionError("channel used outside this owner", self.status())
            except BaseException:
                # Unexpected preflight state means ownership/completion is uncertain.
                # Do not offer a safe-to-free result merely because we did not launch.
                self._poisoned = True
                self._in_flight = True
                _QUARANTINED.append(self)
                raise

            started = time.perf_counter()
            deadline = time.monotonic() + self.timeout_s
            self._in_flight = True  # Even a partial launch can leave DMA accessing RAM.
            try:
                # PYNQ send.transfer flushes the source cache. Prepare every sink first.
                for endpoint in self.receivers:
                    endpoint.channel.transfer(endpoint.buffer)
                self.sender.channel.transfer(self.sender.buffer)
                while True:
                    self._check_status(self.status())
                    if all(e.channel.idle for e in self.endpoints):
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise DmaTransactionError("DMA timeout", self.status())
                    time.sleep(min(self.poll_s, remaining))

                # idle is not cache coherency. PYNQ wait() invalidates received buffers
                # and completes driver bookkeeping. With exclusive ownership it is
                # called only AFTER every channel is idle, so no interrupt is needed.
                for endpoint in self.endpoints:
                    endpoint.channel.wait()
                self._in_flight = False
                self._completed_once = True
                dma_ms = (time.perf_counter() - started) * 1000

                for endpoint in self.receivers:
                    if endpoint.read_length is not None:
                        actual = int(endpoint.read_length())
                        if actual != endpoint.nbytes:
                            raise DmaTransactionError(
                                f"{endpoint.name}: received {actual} bytes, expected {endpoint.nbytes}",
                                self.status())
                # bytes() detaches results from reusable physical DMA buffers.
                outputs = {e.name: memoryview(e.buffer).cast("B").tobytes()
                           for e in self.receivers}
                return outputs, dma_ms
            except BaseException:
                self._poisoned = True
                if self._in_flight:
                    _QUARANTINED.append(self)  # Strong references within this process.
                raise
        finally:
            self._lock.release()
