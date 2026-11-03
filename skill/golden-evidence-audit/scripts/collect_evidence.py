"""Collect versioned report files and same-input timings into JSON and Markdown."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


TIMING_KEYS = ("wns_ns", "tns_ns", "setup_failing", "setup_total", "whs_ns", "ths_ns",
               "hold_failing", "hold_total", "wpws_ns", "tpws_ns", "pulse_failing", "pulse_total")


def header(text):
    result = {}
    for label, key in (("Tool Version", "tool"), ("Date", "date"), ("Design", "design"),
                       ("Device", "device"), ("Design State", "state")):
        match = re.search(r"^\|\s*" + label + r"\s*:\s*(.+)$", text, re.M)
        result[key] = match.group(1).strip() if match else None
    return result


def parse_timing(text):
    result = {key: None for key in TIMING_KEYS}
    # Read ONLY the design summary. Later intra/inter-clock tables have similar headings.
    section = text.split("| Design Timing Summary", 1)
    if len(section) == 2:
        table = section[1].split("| Clock Summary", 1)[0]
        for line in table.splitlines():
            fields = line.split()
            if len(fields) == 12:
                try:
                    values = [float(value) for value in fields]
                except ValueError:
                    continue
                if all(math.isfinite(value) for value in values):
                    result.update(zip(TIMING_KEYS, values))
                    break
    checks = {}
    for name in ("no_clock", "unconstrained_internal_endpoints"):
        found = re.search(r"checking " + name + r" \((\d+)\)", text)
        checks[name] = int(found.group(1)) if found else None
    clocks = []
    clock_section = text.split("| Clock Summary", 1)
    if len(clock_section) == 2:
        for name, period, freq in re.findall(r"^\s*(\S+)\s+\{[^}]+\}\s+([\d.]+)\s+([\d.]+)\s*$",
                                            clock_section[1].split("| Intra Clock Table", 1)[0], re.M):
            clocks.append({"name": name, "period_ns": float(period), "frequency_mhz": float(freq)})
    complete = all(result[key] is not None for key in TIMING_KEYS)
    failed = complete and any(result[key] < 0 for key in ("wns_ns", "whs_ns", "wpws_ns", "tns_ns", "ths_ns", "tpws_ns"))
    failed = failed or any(result[key] is not None and result[key] > 0 for key in ("setup_failing", "hold_failing", "pulse_failing"))
    constrained = all(value == 0 for value in checks.values())
    if failed:
        gate = "FAIL"
    elif complete and constrained and header(text)["state"] == "Routed":
        gate = "PASS_REPORTED_CHECKS"
    else:
        gate = "UNKNOWN"
    return {"metadata": header(text), "metrics": result, "checks": checks, "clocks": clocks,
            "gate": gate, "scope": "reported setup/hold/pulse + two coverage checks; not board proof or a full constraints audit"}


def parse_utilization(text):
    aliases = {"Slice LUTs": "lut", "CLB LUTs": "lut", "Slice Registers": "ff",
               "CLB Registers": "ff", "Block RAM Tile": "bram_tile", "DSPs": "dsp"}
    values = {name: None for name in ("lut", "ff", "bram_tile", "dsp")}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) == 6 and cells[0] in aliases:
            try:
                values[aliases[cells[0]]] = {"used": float(cells[1].replace(",", "")),
                                            "available": float(cells[4].replace(",", "")),
                                            "percent": float(cells[5])}
            except ValueError:
                pass
    return {"metadata": header(text), "metrics": values}


def read_latencies(path, compare_methods):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups, paired, seen = {}, {}, set()
    for row in rows:
        for field in ("sample_id", "method", "boundary"):
            row[field] = (row.get(field) or "").strip()
            if not row[field]:
                raise ValueError(f"latency sample requires nonblank {field}")
        ms = float(row["elapsed_ms"])
        if not math.isfinite(ms) or ms <= 0:
            raise ValueError("latency must be finite and positive")
        digest = row["input_sha256"].lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("each latency sample needs its actual input SHA256")
        key = (row["sample_id"], digest, row["boundary"])
        identity = (row["sample_id"], row["method"])
        if identity in seen:
            raise ValueError("duplicate method/sample; assign each repetition its own sample_id")
        seen.add(identity)
        groups.setdefault((row["method"], row["boundary"]), []).append(ms)
        paired.setdefault(key, {})[row["method"]] = ms
    summaries = [{"method": method, "boundary": boundary, "samples": len(values),
                  "average_ms": statistics.mean(values), "median_ms": statistics.median(values),
                  "min_ms": min(values), "max_ms": max(values)}
                 for (method, boundary), values in groups.items()]
    ratios = []
    if compare_methods:
        numerator, denominator = compare_methods
        for (sample, digest, boundary), methods in paired.items():
            if numerator in methods and denominator in methods:
                ratios.append({"sample_id": sample, "input_sha256": digest, "boundary": boundary,
                               "numerator": numerator, "denominator": denominator,
                               "ratio": methods[numerator] / methods[denominator]})
    return {"summaries": summaries, "matched_ratios": ratios,
            "note": "ratios require identical sample_id, input_sha256 and declared timing boundary; no energy claim"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    config = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    root = manifest_path.parent
    result = {"build_id": config.get("build_id"), "variant": config.get("variant"),
              "artifacts": [], "timing": None, "utilization": None, "latencies": None, "warnings": []}
    for item in config.get("artifacts", []):
        path = (root / item["path"]).resolve()
        entry = {"role": item["role"], "path": item["path"], "sha256": None, "hash_check": "NOT_PINNED"}
        if path.is_file():
            entry["sha256"] = sha256(path)
            if item.get("sha256"):
                entry["hash_check"] = "MATCH" if item["sha256"].lower() == entry["sha256"] else "MISMATCH"
        else:
            entry["hash_check"] = "MISSING"
        result["artifacts"].append(entry)
    for field, parser in (("timing", parse_timing), ("utilization", parse_utilization)):
        if config.get(field):
            path = (root / config[field]).resolve()
            if path.is_file():
                result[field] = parser(path.read_text(encoding="utf-8-sig", errors="replace"))
                result[field]["file_sha256"] = sha256(path)
                result[field]["path"] = config[field]
            else:
                result["warnings"].append(f"missing {field} report: {config[field]}")
    if config.get("latencies"):
        path = (root / config["latencies"]).resolve()
        result["latencies"] = read_latencies(path, config.get("compare_methods"))
        result["latencies"]["file_sha256"] = sha256(path)
    if result["timing"] and result["utilization"]:
        left, right = result["timing"]["metadata"], result["utilization"]["metadata"]
        for key in ("design", "date", "state", "tool"):
            if left[key] is None or right[key] is None:
                result["warnings"].append(f"cannot check common report {key}")
            elif left[key] != right[key]:
                result["warnings"].append(f"report {key} differs; verify reports belong to one implementation")
        if left["device"] is None or right["device"] is None:
            result["warnings"].append("cannot check common report device")
        elif left["device"] != right["device"]:
            result["warnings"].append(
                f"report device text differs: {left['device']} / {right['device']}; "
                "naming or an omitted speed grade may explain this; verify the full part, not an automatic mismatch")
    if not result["build_id"]:
        result["warnings"].append("build_id absent: version UNKNOWN")
    if any(item["hash_check"] != "MATCH" for item in result["artifacts"]) or not result["artifacts"]:
        result["warnings"].append("artifact identity is incomplete; current hashes alone do not prove a matched build")
    result["provenance"] = "manifest records the declared build; matching names/dates/hashes do not prove reports were produced from that bitstream"
    return result


def markdown(data):
    timing = data["timing"] or {}
    tm = timing.get("metrics", {})
    lines = ["# 工程验证证据摘要", "", f"版本：{data['build_id'] or 'UNKNOWN'}",
             f"配置：{data['variant'] or 'UNKNOWN'}", "",
             f"报告内时序检查：{timing.get('gate', 'UNKNOWN')}", "",
             "| 指标 | 值 |", "|---|---|"]
    for key in ("wns_ns", "whs_ns", "tns_ns", "ths_ns", "setup_failing", "hold_failing", "wpws_ns"):
        lines.append(f"| {key} | {tm.get(key) if tm.get(key) is not None else 'UNKNOWN'} |")
    for name, item in (data["utilization"] or {}).get("metrics", {}).items():
        value = f"{item['used']:g} / {item['available']:g} ({item['percent']:g}%)" if item else "UNKNOWN"
        lines.append(f"| {name} | {value} |")
    lines += ["", "## 文件身份", "", "| 角色 | 文件 | SHA256 | 核验 |", "|---|---|---|---|"]
    for item in data["artifacts"]:
        lines.append(f"| {item['role']} | {item['path']} | {item['sha256'] or 'UNKNOWN'} | {item['hash_check']} |")
    if data["latencies"]:
        lines += ["", "## 同一计时口径", "", "| 方法 | 边界 | 样本数 | 平均 ms | 中位数 ms |", "|---|---|---|---|---|"]
        for item in data["latencies"]["summaries"]:
            lines.append(f"| {item['method']} | {item['boundary']} | {item['samples']} | {item['average_ms']:.3f} | {item['median_ms']:.3f} |")
        pairs = data["latencies"]["matched_ratios"]
        lines += ["", f"可比较的同输入样本对：{len(pairs)}。"]
        if pairs:
            lines.append("逐对耗时比：" + ", ".join(f"{p['sample_id']}: {p['ratio']:.3f}x" for p in pairs))
        else:
            lines.append("无匹配样本，不计算加速比。")
    lines += ["", "## 待核实项", ""]
    lines.extend("- " + text for text in data["warnings"])
    lines += ["", "本摘要不证明上板通过、能效优势或识别精度。正 WHS 表示报告中的保持检查通过；数值小不等同于必然死锁。",
              "文件哈希用于身份追溯，不能单独证明 bitstream、报告和源码同源。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = collect(args.manifest)
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(2, f"INPUT ERROR: {exc}\n")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "evidence.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output / "evidence.md").write_text(markdown(data), encoding="utf-8")
    print(args.output / "evidence.md")
    print("Collected evidence; report generation is not a hardware PASS.")


if __name__ == "__main__":
    main()
