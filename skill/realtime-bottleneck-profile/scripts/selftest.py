"""合成时钟验证重叠区间、模式隔离和错误帧；不需要硬件。"""
import copy
import unittest
from frame_probe import FrameProbe
from analyze_trace import analyze, union_seconds, markdown


class ProbeTests(unittest.TestCase):
    def record(self):
        clock = [0.0]
        p = FrameProbe(1, clock=lambda: clock[0])
        with p.stage("outer"):
            clock[0] = .01
            with p.stage("inner"):
                clock[0] = .03
            clock[0] = .04
        clock[0] = .05
        return p.finish()

    def test_nested_not_double_counted(self):
        group = analyze([self.record()])["demo"]
        self.assertAlmostEqual(group["loops"][0], 50)
        self.assertAlmostEqual(group["uncovered"][0], 10)

    def test_intervals(self):
        self.assertEqual(union_seconds([(1, 4), (2, 5), (7, 8)]), 5)
        self.assertEqual(union_seconds([]), 0)

    def test_modes_stay_separate(self):
        record = self.record()
        other = copy.deepcopy(record)
        other["mode"] = "benchmark"
        groups = analyze([record, other])
        self.assertEqual(set(groups), {"demo", "benchmark"})
        self.assertIn("不等于", markdown(groups))

    def test_failure_excluded(self):
        clock = [0.0]
        p = FrameProbe(2, clock=lambda: clock[0])
        with self.assertRaises(RuntimeError):
            with p.stage("call"):
                clock[0] = .02
                raise RuntimeError("模拟计算错误")
        group = analyze([p.finish()])["demo"]
        self.assertEqual(group["errors"], 1)
        self.assertEqual(group["loops"], [])

    def test_invalid_clock(self):
        for value in [float("nan"), float("inf"), -1]:
            record = self.record()
            record["loop_end"] = value
            with self.assertRaises(ValueError):
                analyze([record])

    def test_unfinished_stage_and_late_span(self):
        p = FrameProbe(3)
        with p.stage("worker", lane="worker"):
            with self.assertRaises(RuntimeError):
                p.finish()
        record = p.finish()
        self.assertEqual(len(record["spans"]), 1)
        with self.assertRaises(RuntimeError):
            p.add_span("late_worker", 0, 1)


if __name__ == "__main__":
    unittest.main()
