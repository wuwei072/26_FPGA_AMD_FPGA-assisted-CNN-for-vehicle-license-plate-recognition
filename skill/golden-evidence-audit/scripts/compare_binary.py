"""Compare a declared golden output with a captured output; standard library only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct


FORMATS = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I",
           "i32": "i", "f32": "f", "f64": "d"}


def read_values(path, dtype, shape, byteorder):
    raw = Path(path).read_bytes()
    fmt = ("<" if byteorder == "little" else ">") + FORMATS[dtype]
    expected_size = math.prod(shape) * struct.calcsize(fmt)
    if len(raw) != expected_size:
        raise ValueError(f"{path}: expected {expected_size} bytes, got {len(raw)}")
    return [item[0] for item in struct.iter_unpack(fmt, raw)], hashlib.sha256(raw).hexdigest()


def coordinates(index, shape):
    result = []
    for size in reversed(shape):
        index, remainder = divmod(index, size)
        result.append(remainder)
    return list(reversed(result))


def compare(expected, actual, dtype, shape, byteorder="little", threshold=None,
            on_value=255, atol=0.0, rtol=0.0):
    if not shape or any(n <= 0 for n in shape):
        raise ValueError("shape dimensions must be positive")
    if not all(math.isfinite(value) and value >= 0 for value in (atol, rtol)):
        raise ValueError("tolerances must be finite and nonnegative")
    if threshold is not None and not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    reference, golden_hash = read_values(expected, dtype, shape, byteorder)
    observed, actual_hash = read_values(actual, dtype, shape, byteorder)
    if threshold is not None:
        if any(not math.isfinite(value) for value in reference):
            raise ValueError("cannot threshold a golden output containing NaN or infinity")
        # Only transform the reference. Transforming captured data would hide faults.
        reference = [on_value if value >= threshold else 0 for value in reference]
    mismatches, first = 0, []
    for index, (want, got) in enumerate(zip(reference, observed)):
        equal = got == want if atol == rtol == 0 else math.isclose(got, want, abs_tol=atol, rel_tol=rtol)
        if not equal:
            mismatches += 1
            if len(first) < 8:
                first.append({"index": index, "coordinates": coordinates(index, shape),
                              "expected": want if math.isfinite(want) else str(want),
                              "actual": got if math.isfinite(got) else str(got)})
    return {"status": "PASS" if mismatches == 0 else "FAIL", "dtype": dtype,
            "shape": shape, "byteorder": byteorder, "threshold": threshold,
            "on_value": on_value if threshold is not None else None,
            "atol": atol, "rtol": rtol, "elements": len(reference),
            "mismatches": mismatches, "first_mismatches": first,
            "expected_sha256": golden_hash, "actual_sha256": actual_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--dtype", choices=FORMATS, required=True)
    parser.add_argument("--shape", required=True, help="row-major dimensions, e.g. 128,256 or 12")
    parser.add_argument("--byteorder", choices=("little", "big"), default="little")
    parser.add_argument("--threshold", type=float, help="explicitly convert GOLDEN magnitude to binary using >=")
    parser.add_argument("--on-value", type=int, default=255)
    parser.add_argument("--atol", type=float, default=0)
    parser.add_argument("--rtol", type=float, default=0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.expected, args.actual, args.dtype,
                         [int(n) for n in args.shape.split(",")], args.byteorder,
                         args.threshold, args.on_value, args.atol, args.rtol)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"INPUT ERROR: {exc}\n")
    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)
    if args.json:
        args.json.write_text(output + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
