"""离线检查本技能包及合成测试；不启动应用，不访问设备和网络。"""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

NAMES = ("host-target-bringup", "dma-transaction-debug",
         "realtime-bottleneck-profile", "golden-evidence-audit")


def inspect_files(root):
    errors = []
    for name in NAMES:
        folder = root / name
        for relative in ("SKILL.md", "README.md", "scripts/selftest.py"):
            if not (folder / relative).is_file():
                errors.append(f"缺少 {name}/{relative}")
        entry = folder / "SKILL.md"
        if entry.is_file():
            text = entry.read_text(encoding="utf-8-sig")
            front = re.match(r"\A---\s*\n(.*?)\n---(?:\n|$)", text, re.S)
            if not front:
                errors.append(f"{name}: 缺少 frontmatter")
            else:
                # 本包只采用单行 name/description，不声称是通用 YAML 解析器。
                fields = dict(line.split(":", 1) for line in front[1].splitlines() if ":" in line)
                if fields.get("name", "").strip().strip('"\'') != name:
                    errors.append(f"{name}: name 与目录不符")
                if not fields.get("description", "").strip():
                    errors.append(f"{name}: 缺少 description")
                if "TODO" in front[1]:
                    errors.append(f"{name}: 存在未完成占位符")
    for script in root.rglob("*.py"):
        try:
            ast.parse(script.read_text(encoding="utf-8-sig"), filename=str(script))
        except (SyntaxError, UnicodeError) as exc:
            errors.append(str(exc))
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            local = target.split("#", 1)[0]
            if not (path.parent / local).exists():
                errors.append(f"{path.relative_to(root)}: 失效链接 {target}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="可选 JSON 结果文件")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    results = {"hardware_accessed": False, "errors": inspect_files(root), "suites": []}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for name in NAMES:
        folder = root / name
        test = folder / "scripts" / "selftest.py"
        if not test.exists():
            continue
        proc = subprocess.run([sys.executable, "-B", str(test)], cwd=str(folder), env=env,
                              text=True, encoding="utf-8", errors="replace", capture_output=True)
        output = proc.stdout + proc.stderr
        results["suites"].append(dict(name=name, passed=proc.returncode == 0, output=output))
        print(("PASS " if proc.returncode == 0 else "FAIL ") + name)
        if proc.returncode:
            print(output)
    results["passed"] = (not results["errors"] and len(results["suites"]) == len(NAMES)
                         and all(s["passed"] for s in results["suites"]))
    for error in results["errors"]:
        print("FAIL", error)
    if args.output:
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("离线校验通过；不代表硬件验证。" if results["passed"] else "存在未通过项。")
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
