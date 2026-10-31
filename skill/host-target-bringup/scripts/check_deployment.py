"""Check one machine's deployment files; never start processes or program hardware."""
import argparse
import hashlib
import json
import platform
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect(plan, role, root, system=None):
    """Return JSON-compatible findings for the selected host or target role."""
    config = plan["roles"][role]
    root = Path(root).resolve()
    actual_os = (system or platform.system()).lower()
    expected_os = config["os"].lower()
    checks = [{"item": "operating_system", "ok": actual_os == expected_os,
               "actual": actual_os, "expected": expected_os},
              {"item": "working_directory", "ok": root.is_dir(), "path": str(root)}]
    inventory = {}
    names = set(config.get("files", []))
    expected_hashes = config.get("sha256", {})
    names.update(expected_hashes)
    paired_names = set()
    for pair in config.get("artifact_pairs", []):
        stem = pair["stem"]
        paired_names.update(stem + suffix for suffix in pair["suffixes"])
    names.update(paired_names)
    for name in sorted(names):
        path = root / name
        exists = path.is_file()
        checks.append({"item": "file", "name": name, "path": str(path), "ok": exists})
        if exists:
            digest = sha256(path)
            inventory[name] = {"bytes": path.stat().st_size, "sha256": digest}
            if name in expected_hashes:
                checks.append({"item": "sha256", "name": name,
                               "ok": digest.lower() == expected_hashes[name].lower(),
                               "expected": expected_hashes[name], "actual": digest})
    warnings = []
    if paired_names.difference(expected_hashes):
        warnings.append("Trusted build hashes were not supplied for all paired artifacts. "
                        "This does not prove they came from the same build.")
    return {"role": role, "root": str(root), "ok": all(c["ok"] for c in checks),
            "checks": checks, "files": inventory, "warnings": warnings,
            "startup_hint": config.get("startup_hint", "")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--role", required=True, help="Role name declared in the plan")
    parser.add_argument("--root", type=Path, required=True, help="Actual upload/application folder")
    parser.add_argument("--out", type=Path, help="Optional JSON result; parent directory must exist")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    result = inspect(plan, args.role, args.root)
    print("PASS" if result["ok"] else "FAIL", "role=" + args.role, "root=" + result["root"])
    for check in result["checks"]:
        if not check["ok"]:
            print("  FAIL:", json.dumps(check, ensure_ascii=False))
    for warning in result["warnings"]:
        print("  NOTE:", warning)
    if result["startup_hint"]:
        print("  STARTUP HINT (not executed):", result["startup_hint"])
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
