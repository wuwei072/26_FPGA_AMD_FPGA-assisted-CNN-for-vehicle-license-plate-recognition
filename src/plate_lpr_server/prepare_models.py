"""模型文件准备"""
import re
import sys
import zipfile
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models" / "20230229" / "onnx"
MODEL_NAMES = ("y5fu_320x_sim.onnx", "rpv3_mdict_160_r3.onnx", "litemodel_cls_96x_r1.onnx")
MARKER = "# LOCAL_ONLY: automatic model download disabled"


def main():
    if Path(sys.prefix).resolve() != ROOT / "venv":
        raise RuntimeError("请使用本目录虚拟环境运行")

    source_path = Path(distribution("hyperlpr3").locate_file("hyperlpr3/hyperlpr3.py")).resolve()
    if not source_path.is_relative_to(ROOT / "venv"):
        raise RuntimeError("依赖路径不正确")
    source = source_path.read_text(encoding="utf-8")
    if MARKER not in source:
        source, count = re.subn(r"(?m)^initialization\(\)[ \t]*$", MARKER, source)
        if count != 1:
            raise RuntimeError("HyperLPR3 版本不匹配")
        source = source.replace(
            "from .config.configuration import initialization",
            "# Use local models.",
        )
        source_path.write_text(source, encoding="utf-8")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    missing = [name for name in MODEL_NAMES if not (MODEL_DIR / name).is_file()]
    if missing:
        with zipfile.ZipFile(ROOT / "models" / "20230229.zip") as archive:
            members = {
                name.replace("\\", "/").split("/")[-1]: name
                for name in archive.namelist()
            }
            for name in missing:
                (MODEL_DIR / name).write_bytes(archive.read(members[name]))
    print("模型准备完成")

if __name__ == "__main__":
    main()
