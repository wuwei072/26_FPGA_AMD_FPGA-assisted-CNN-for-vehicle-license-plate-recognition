"""Create explicitly synthetic inputs for trying the comparison/report commands."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from selftest import TIMING, UTIL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    magnitude = bytes([0, 32, 64, 80, 96, 255])
    (args.output / "magnitude.bin").write_bytes(magnitude)
    (args.output / "captured.bin").write_bytes(bytes([0, 0, 0, 255, 255, 255]))
    (args.output / "timing.rpt").write_text(TIMING, encoding="utf-8")
    (args.output / "utilization.rpt").write_text(UTIL, encoding="utf-8")
    digest = hashlib.sha256(magnitude).hexdigest()
    with (args.output / "latencies.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_id", "input_sha256", "method", "boundary", "elapsed_ms"])
        writer.writerows([["demo-1", digest, "cpu", "input-ready-to-result-ready", 20],
                          ["demo-1", digest, "fpga", "input-ready-to-result-ready", 5]])
    manifest = {"build_id": "SYNTHETIC-DEMO-NOT-A-HARDWARE-RESULT", "variant": "synthetic",
                "artifacts": [{"role": "golden", "path": "magnitude.bin", "sha256": digest}],
                "timing": "timing.rpt", "utilization": "utilization.rpt", "latencies": "latencies.csv",
                "compare_methods": ["cpu", "fpga"]}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Synthetic demo created:", args.output)


if __name__ == "__main__":
    main()
