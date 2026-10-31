"""生成合成示例日志；这些数字不代表板端性能。"""
import argparse
import json
from pathlib import Path
from frame_probe import FrameProbe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("w", encoding="utf-8") as f:
        for frame_id in range(10):
            now = [float(frame_id)]
            probe = FrameProbe(frame_id, mode="synthetic-demo", clock=lambda: now[0])
            for name, seconds in [("capture", .02), ("accelerator_call", .01), ("encode", .04), ("ui_submit", .01)]:
                with probe.stage(name):
                    now[0] += seconds
            now[0] += .005
            f.write(json.dumps(probe.finish()) + "\n")
    print("已生成合成示例：", args.output)


if __name__ == "__main__":
    main()
