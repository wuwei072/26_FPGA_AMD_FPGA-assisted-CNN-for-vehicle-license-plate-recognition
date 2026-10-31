"""Hardware-free lifecycle tests. They do not validate a real DMA or cache controller."""
from array import array
import unittest

from dma_transaction import Endpoint, PollingTransaction, DmaTransactionError


class FakeChannel:
    def __init__(self, name, log, delay=2, fail_launch=False, error=0):
        self.name, self.log, self.delay = name, log, delay
        self.fail_launch, self.error = fail_launch, error
        self.active = False
        self.buffer = None
        self.remaining = 0

    def transfer(self, buffer):
        self.log.append("transfer:" + self.name)
        if self.fail_launch:
            raise RuntimeError("injected launch failure")
        self.buffer, self.active, self.remaining = buffer, True, self.delay
        if self.name == "input":
            self.log.append("flush:input")

    @property
    def idle(self):
        if not self.active:
            # Match the initial PYNQ quirk: not idle before the first transfer.
            return self.buffer is not None
        self.remaining -= 1
        return self.remaining <= 0

    def status(self):
        return self.error if self.active else 0

    def wait(self):
        assert self.remaining <= 0, "wait called before completion"
        self.log.append("wait:" + self.name)
        if self.name != "input":
            self.buffer[:] = array("B", [17] * len(self.buffer))
            self.log.append("invalidate:" + self.name)
        self.active = False


def fixture(**options):
    log = []
    send = FakeChannel("input", log, **options.get("send", {}))
    one = FakeChannel("result", log, **options.get("one", {}))
    two = FakeChannel("aux", log, **options.get("two", {}))
    buffers = [array("B", [0] * n) for n in (16, 8, 32)]
    endpoints = [Endpoint("input", send, buffers[0], send.status),
                 Endpoint("result", one, buffers[1], one.status,
                          lambda: options.get("length", 8)),
                 Endpoint("aux", two, buffers[2], two.status, lambda: 32)]
    transaction = PollingTransaction(endpoints[0], endpoints[1:],
                                     timeout_s=0.2, poll_s=0.001)
    return transaction, log, buffers


class TransactionTests(unittest.TestCase):
    def test_order_cache_copy_and_reuse(self):
        tx, log, buffers = fixture(two={"delay": 4})
        out, elapsed = tx.run()
        self.assertEqual(log[:3], ["transfer:result", "transfer:aux", "transfer:input"])
        self.assertIn("flush:input", log)
        self.assertIn("invalidate:result", log)
        self.assertIn("invalidate:aux", log)
        self.assertEqual(out["result"], bytes([17] * 8))
        buffers[1][0] = 99
        self.assertEqual(out["result"][0], 17)
        self.assertTrue(tx.safe_to_release)
        self.assertGreater(elapsed, 0)
        tx.run()

    def test_timeout_retains_buffers_and_blocks_reuse(self):
        tx, log, _ = fixture(two={"delay": 10000})
        with self.assertRaisesRegex(DmaTransactionError, "timeout"):
            tx.run()
        self.assertFalse(tx.safe_to_release)
        self.assertNotIn("wait:aux", log)
        with self.assertRaisesRegex(RuntimeError, "faulted"):
            tx.run()

    def test_dma_error(self):
        tx, _, _ = fixture(one={"error": 0x20})
        with self.assertRaisesRegex(DmaTransactionError, "slave error"):
            tx.run()
        self.assertFalse(tx.safe_to_release)

    def test_partial_launch_is_quarantined(self):
        tx, log, _ = fixture(two={"fail_launch": True})
        with self.assertRaisesRegex(RuntimeError, "launch failure"):
            tx.run()
        self.assertFalse(tx.safe_to_release)
        self.assertNotIn("transfer:input", log)

    def test_short_packet_is_not_success(self):
        tx, _, _ = fixture(length=7)
        with self.assertRaisesRegex(DmaTransactionError, "received 7 bytes"):
            tx.run()
        self.assertTrue(tx.safe_to_release)  # All channels completed despite bad data.
        with self.assertRaisesRegex(RuntimeError, "faulted"):
            tx.run()

    def test_reentry(self):
        tx, _, _ = fixture()
        tx._lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "already running"):
                tx.run()
        finally:
            tx._lock.release()

    def test_foreign_activity_prevents_free(self):
        tx, _, _ = fixture()
        tx.run()
        foreign = tx.receivers[0].channel
        foreign.active, foreign.remaining = True, 10000
        with self.assertRaisesRegex(DmaTransactionError, "outside this owner"):
            tx.run()
        self.assertFalse(tx.safe_to_release)
        with self.assertRaisesRegex(RuntimeError, "faulted"):
            tx.run()


if __name__ == "__main__":
    unittest.main(verbosity=2)
