"""分析同一时钟上的阶段区间；嵌套/并行不重复计数。仅使用标准库。"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("时间必须是有限数字")
    return value


def union_seconds(intervals):
    total = 0.0
    left = right = None
    for start, end in sorted(intervals):
        if left is None:
            left, right = start, end
        elif start > right:
            total += right - left
            left, right = start, end
        else:
            right = max(right, end)
    return total + (0.0 if left is None else right - left)


def analyze(records):
    modes = defaultdict(lambda: dict(stages=defaultdict(list), loops=[], uncovered=[], errors=0))
    for record in records:
        if record.get("schema") != 1:
            raise ValueError("需要 schema=1 的 FrameProbe 日志")
        start, end = finite_number(record["loop_start"]), finite_number(record["loop_end"])
        if end < start:
            raise ValueError("loop_end 早于 loop_start")
        mode = record["mode"]
        if not isinstance(mode, str) or not mode:
            raise ValueError("mode 必须是非空字符串")
        group = modes[mode]
        intervals = []
        frame_ok = True
        for span in record["spans"]:
            a, b = finite_number(span["start"]), finite_number(span["end"])
            if b < a:
                raise ValueError("阶段时间顺序错误")
            ok = span["ok"]
            if not isinstance(ok, bool):
                raise ValueError("ok 必须为布尔值")
            key = str(span["name"]) + " @ " + str(span["lane"])
            if ok:
                group["stages"][key].append((b - a) * 1000)
            else:
                frame_ok = False
                group["errors"] += 1
            clipped = (max(start, a), min(end, b))
            if clipped[1] >= clipped[0]:
                intervals.append(clipped)
        if frame_ok:
            group["loops"].append((end - start) * 1000)
            group["uncovered"].append(max(0.0, end - start - union_seconds(intervals)) * 1000)
    return modes


def summary(values):
    if not values:
        return "0 | -- | -- | --"
    ordered = sorted(values)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return f"{len(values)} | {statistics.mean(values):.3f} | {p95:.3f} | {max(values):.3f}"


def markdown(modes):
    lines = ["# 主机流水线计时", "", "时间单位：ms。P95 使用 nearest-rank；样本少时不代表稳定尾延迟。", "",
             "阶段可以嵌套或重叠，不能逐行求和。循环时间不等于实际屏幕显示延迟或帧率。", ""]
    for mode, group in sorted(modes.items()):
        lines += [f"## 模式：{mode}", "", "| 阶段 | 样本数 | 平均 | P95 | 最大 |", "|---|---:|---:|---:|---:|"]
        lines.append("| 完整循环（无失败阶段） | " + summary(group["loops"]) + " |")
        for key, values in sorted(group["stages"].items(), key=lambda item: -statistics.mean(item[1])):
            lines.append("| " + key.replace("|", "/") + " | " + summary(values) + " |")
        lines += ["| 循环内未覆盖区间 | " + summary(group["uncovered"]) + " |", "",
                  f"失败阶段数：{group['errors']}；失败阶段不混入阶段均值，其所在帧不计入循环均值。", ""]
    lines += ["相机内部缓冲、跨机网络、显示器呈现未由本日志证明。参考计算与演示模式应分别采样。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        with args.trace.open(encoding="utf-8-sig") as f:
            result = markdown(analyze(json.loads(line) for line in f if line.strip()))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, "日志无法分析：" + str(exc) + "\n")
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
