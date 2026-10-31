"""Local, synthetic checks. Does not access FPGA, camera, or network."""
import csv
import json
from pathlib import Path
import struct
import tempfile
import unittest

from compare_binary import compare
from collect_evidence import collect, markdown, parse_timing, parse_utilization, read_latencies


TIMING = """| Tool Version : Vivado synthetic fixture
| Date : synthetic-run-A
| Design : demo
| Design State : Routed
checking no_clock (0)
checking unconstrained_internal_endpoints (0)
| Design Timing Summary
 WNS(ns) TNS(ns) Other columns
 2.500 0.000 0 100 0.025 0.000 0 100 4.000 0.000 0 100
| Clock Summary
clk {0.000 5.000} 10.000 100.000
| Intra Clock Table
"""
UTIL = """| Tool Version : Vivado synthetic fixture
| Date : synthetic-run-A
| Design : demo
| Design State : Routed
| Slice LUTs | 123 | 0 | 0 | 1000 | 12.30 |
| Slice Registers | 456 | 0 | 0 | 2000 | 22.80 |
| Block RAM Tile | 2.5 | 0 | 0 | 100 | 2.50 |
| DSPs | 0 | 0 | 0 | 80 | 0.00 |
"""


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_semantics_are_explicit(self):
        want, got = self.root / "gold.bin", self.root / "got.bin"
        want.write_bytes(bytes([0, 32, 64, 80, 96, 255]))
        got.write_bytes(bytes([0, 0, 0, 255, 255, 255]))
        self.assertEqual(compare(want, got, "u8", [2, 3])["mismatches"], 4)
        self.assertEqual(compare(want, got, "u8", [2, 3], threshold=80)["status"], "PASS")
        got.write_bytes(bytes([0, 0, 1, 255, 255, 255]))
        result = compare(want, got, "u8", [2, 3], threshold=80)
        self.assertEqual(result["mismatches"], 1)
        self.assertEqual(result["first_mismatches"][0]["coordinates"], [0, 2])

    def test_shape_and_endianness(self):
        a, b = self.root / "a.bin", self.root / "b.bin"
        a.write_bytes(struct.pack(">2H", 7, 1024))
        b.write_bytes(a.read_bytes())
        self.assertEqual(compare(a, b, "u16", [2], "big")["status"], "PASS")
        with self.assertRaises(ValueError):
            compare(a, b, "u16", [3])

    def test_tolerance_never_accepts_nan(self):
        a, b = self.root / "a.bin", self.root / "b.bin"
        a.write_bytes(struct.pack("<2f", 1, 2))
        b.write_bytes(struct.pack("<2f", 1.001, float("nan")))
        result = compare(a, b, "f32", [2], atol=.01)
        self.assertEqual(result["mismatches"], 1)
        json.dumps(result, allow_nan=False)
        with self.assertRaises(ValueError):
            compare(a, b, "f32", [2], atol=float("inf"))

    def test_threshold_cannot_hide_nonfinite_golden(self):
        a, b = self.root / "a.bin", self.root / "b.bin"
        b.write_bytes(struct.pack("<f", 0))
        for value in (float("nan"), float("inf"), -float("inf")):
            a.write_bytes(struct.pack("<f", value))
            with self.assertRaises(ValueError):
                compare(a, b, "f32", [1], threshold=80)

    def test_report_metrics_and_unknown(self):
        result = parse_timing(TIMING)
        self.assertEqual(result["metrics"]["whs_ns"], .025)
        self.assertEqual(result["gate"], "PASS_REPORTED_CHECKS")
        self.assertEqual(result["clocks"][0]["frequency_mhz"], 100)
        self.assertEqual(parse_timing(TIMING.replace("2.500", "-0.100"))["gate"], "FAIL")
        self.assertEqual(parse_timing("changed report format")["gate"], "UNKNOWN")
        self.assertEqual(parse_utilization(UTIL)["metrics"]["bram_tile"]["used"], 2.5)
        self.assertIsNone(parse_utilization("")["metrics"]["dsp"])

    def test_hash_and_cross_version_warnings(self):
        (self.root / "timing.rpt").write_text(TIMING)
        (self.root / "util.rpt").write_text(UTIL.replace("synthetic-run-A", "synthetic-run-B"))
        (self.root / "image.bin").write_bytes(b"demo")
        manifest = {"timing": "timing.rpt", "utilization": "util.rpt",
                    "artifacts": [{"role": "input", "path": "image.bin", "sha256": "0" * 64}]}
        p = self.root / "manifest.json"
        p.write_text(json.dumps(manifest))
        result = collect(p)
        self.assertEqual(result["artifacts"][0]["hash_check"], "MISMATCH")
        self.assertTrue(any("date differs" in text for text in result["warnings"]))
        self.assertIn("UNKNOWN", markdown(result))

    def test_device_text_difference_requires_review(self):
        (self.root / "timing.rpt").write_text(TIMING + "| Device : 7z020-clg400\n")
        manifest = {"build_id": "synthetic", "timing": "timing.rpt", "utilization": "util.rpt"}
        p = self.root / "manifest.json"
        p.write_text(json.dumps(manifest))
        for part in ("xc7z020clg400-1", "xc7z010clg225-1"):
            (self.root / "util.rpt").write_text(UTIL + "| Device : " + part + "\n")
            result = collect(p)
            self.assertTrue(any("device text differs" in text for text in result["warnings"]))
            self.assertTrue(any("not an automatic mismatch" in text for text in result["warnings"]))
            self.assertEqual(result["timing"]["gate"], "PASS_REPORTED_CHECKS")

    def test_only_same_input_and_boundary_can_pair(self):
        p = self.root / "times.csv"
        with p.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sample_id", "input_sha256", "method", "boundary", "elapsed_ms"])
            writer.writerows([["1", "a" * 64, "cpu", "input-to-result", 20],
                              ["1", "a" * 64, "fpga", "input-to-result", 5],
                              ["2", "b" * 64, "cpu", "input-to-result", 30],
                              ["2", "c" * 64, "fpga", "input-to-result", 5],
                              ["3", "a" * 64, "cpu", "input-to-result", 30],
                              ["3", "a" * 64, "fpga", "dma-only", 5]])
        result = read_latencies(p, ["cpu", "fpga"])
        self.assertEqual(len(result["matched_ratios"]), 1)
        self.assertEqual(result["matched_ratios"][0]["ratio"], 4)

    def test_duplicate_method_sample_is_not_another_repetition(self):
        p = self.root / "times.csv"
        with p.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sample_id", "input_sha256", "method", "boundary", "elapsed_ms"])
            writer.writerows([["1", "a" * 64, "cpu", "input-to-result", 20],
                              ["1", "b" * 64, "cpu", "another-boundary", 10]])
        with self.assertRaises(ValueError):
            read_latencies(p, ["cpu", "fpga"])

    def test_blank_identity_fields_cannot_pair(self):
        p = self.root / "times.csv"
        fields = ["sample_id", "input_sha256", "method", "boundary", "elapsed_ms"]
        for field in ("sample_id", "method", "boundary"):
            row = dict(zip(fields, ["1", "a" * 64, "cpu", "input-to-result", 20]))
            row[field] = "   "
            with p.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(row)
            with self.assertRaises(ValueError):
                read_latencies(p, ["cpu", "fpga"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
