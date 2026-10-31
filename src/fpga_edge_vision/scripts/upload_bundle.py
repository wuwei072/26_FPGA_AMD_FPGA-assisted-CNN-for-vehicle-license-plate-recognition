"""整理Dashboard上传包；Golden验证独立放在validation目录。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
VECTOR_STEMS = ("single_target", "multi_target", "noise_target")
MAIN_SCRIPTS = (
    "software/pynq/edge_dma_runtime.py",
    "software/pynq/pynq_video_server.py",
    "software/pynq/video_protocol.py",
    "software/python_ref/opencv_benchmark.py",
)



def digest(path):
    """记录内容摘要，识别同名文件变化并验证回退文件未变。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UploadBundle:
    def __init__(self, project_root):
        self.root = Path(project_root).resolve()
        self.upload = self.root / "upload_to_board"
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
        self.archive = self.root / "results" / "upload_archive" / stamp
        self.errors = []

    def check_path(self, path):
        # 移动、备份和覆盖前核验绝对路径，拒绝通过链接越出工程。
        path = Path(path)
        path.resolve().relative_to(self.root)
        return path

    def archive_copy(self, path):
        target = self.archive / path.relative_to(self.upload)
        self.check_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    def move(self, source, destination):
        self.check_path(source)
        self.check_path(destination)
        if not source.exists():
            return
        if destination.exists():
            # 不覆盖用户自行整理出的不同版本，也不删除原件。
            if source.is_file() and destination.is_file() and digest(source) == digest(destination):
                destination = self.archive / source.relative_to(self.upload)
                self.check_path(destination)
            else:
                raise ValueError("目标已存在，请核对两个版本：{} / {}".format(source, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        print("[MOVE] {} -> {}".format(source.relative_to(self.root), destination.relative_to(self.root)))

    def migrate(self):
        """只移动已知文件，未知文件、板端日志和结果目录不受影响。"""
        for name in ("sobel.bit", "sobel.hwh", "sobel_demo.ipynb"):
            self.move(self.upload / name, self.root / "results/roi_only_fallback" / name)
        self.move(self.upload / "backup_roi_only", self.root / "results/roi_only_fallback")
        self.move(self.upload / "edge_return_test.py", self.upload / "validation/edge_return_test.py")
        for stem in VECTOR_STEMS:
            for kind in ("input", "expected"):
                name = "{}_640x480_{}.bin".format(stem, kind)
                self.move(self.upload / name, self.upload / "validation" / name)
        for name in ("upload_readme.md", "edge_return_readme.md"):
            self.move(self.upload / name, self.archive / name)

    def copy(self, source, target, preserve=False):
        source, target = Path(source), self.check_path(target)
        if preserve and target.is_file():
            print("[KEEP]", target.relative_to(self.upload))
            return
        if not source.is_file():
            message = "缺少源文件：{}".format(source)
            self.errors.append(message)
            print("[MISSING]", message)
            return
        if target.is_file():
            if digest(source) == digest(target):
                return
            self.archive_copy(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print("[COPY]", target.relative_to(self.upload))

    def copy_pair(self, source_dir, target_dir, stem, preserve=False):
        """硬件文件必须成对复制，缺少一方时不混入另一构建的产物。"""
        sources = [source_dir / (stem + suffix) for suffix in (".bit", ".hwh")]
        targets = [target_dir / path.name for path in sources]
        if preserve and any(path.exists() for path in targets):
            if all(path.is_file() for path in targets):
                print("[KEEP] 回退Overlay：", target_dir)
            else:
                self.errors.append("回退Overlay缺少配对文件；未自动混配：{}".format(target_dir))
            return
        if not all(path.is_file() for path in sources):
            for path in sources:
                if not path.is_file():
                    print("[MISSING]", path)
                    self.errors.append("缺少硬件产物：{}".format(path))
            return
        for source, target in zip(sources, targets):
            self.copy(source, target)

    def prepare(self, edge_only=False):
        self.check_path(self.upload)
        self.upload.mkdir(parents=True, exist_ok=True)
        self.migrate()
        self.copy(self.root / "docs/board_upload_guide.md", self.upload / "README.md")
        self.copy_pair(self.root / "hardware/vivado/sobel_edge_system/output", self.upload, "sobel_edge")
        for relative in MAIN_SCRIPTS:
            self.copy(self.root / relative, self.upload / Path(relative).name)
        validation = self.upload / "validation"
        self.copy(self.root / "software/pynq/edge_return_test.py", validation / "edge_return_test.py")
        for stem in VECTOR_STEMS:
            for kind in ("input", "expected"):
                name = "{}_640x480_{}.bin".format(stem, kind)
                self.copy(self.root / "hardware/sim/vectors" / name, validation / name)

        return self.report()

    def report(self):
        required = ["sobel_edge.bit", "sobel_edge.hwh"] + [Path(p).name for p in MAIN_SCRIPTS]
        required += ["validation/edge_return_test.py"]
        required += ["validation/{}_640x480_{}.bin".format(stem, kind)
                     for stem in VECTOR_STEMS for kind in ("input", "expected")]
        missing = [name for name in required if not (self.upload / name).is_file()]
        for name in required:
            path = self.upload / name
            if path.is_file() and name.endswith(".bin") and path.stat().st_size != 307200:
                self.errors.append("向量必须是307200字节：{}".format(name))
        hwh = self.upload / "sobel_edge.hwh"
        if hwh.is_file():
            try:
                instances = {node.get("INSTANCE") for node in ET.parse(hwh).iter("MODULE")}
                if not {"axi_dma_0", "axi_dma_edge"}.issubset(instances):
                    self.errors.append("sobel_edge.hwh缺少双DMA实例，不能启动Dashboard")
            except (OSError, ET.ParseError) as exc:
                self.errors.append("HWH无法解析：{}".format(exc))
        records = {}
        for path in sorted(self.upload.rglob("*")):
            if path.is_file() and path.name != "UPLOAD_MANIFEST.json":
                records[path.relative_to(self.upload).as_posix()] = {
                    "bytes": path.stat().st_size, "sha256": digest(path)}
        manifest = {
            "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "board_directory": "/home/xilinx/jupyter_notebooks/fpga_edge_vision",
            "main_package_complete": not missing and not self.errors,
            "missing_main_files": missing,
            "errors": self.errors,
            "board_validation": "更换Overlay后运行validation/edge_return_test.py；打包不代表硬件验证通过",
            "archive_directory": str(self.archive) if self.archive.exists() else None,
            "files": records,
        }
        destination = self.check_path(self.upload / "UPLOAD_MANIFEST.json")
        destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("\n=== Upload package ===")
        print("Main directory:", self.upload)
        print("Guide:", self.upload / "README.md")
        for name in missing:
            print("[MISSING MAIN]", name)
        for error in self.errors:
            print("[WARN]", error)
        print("READY TO UPLOAD" if manifest["main_package_complete"] else "INCOMPLETE: see README.md and UPLOAD_MANIFEST.json")
        if self.archive.exists():
            print("Archived original files:", self.archive)
        return 0 if manifest["main_package_complete"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="整理PYNQ上传目录；缺少双DMA硬件产物时返回1")
    parser.add_argument("--edge-only", action="store_true", help="兼容原命令；与默认刷新相同，不再生成旧演示")
    args = parser.parse_args(argv)
    try:
        return UploadBundle(ROOT).prepare(edge_only=args.edge_only)
    except (OSError, ValueError) as exc:
        print("[ERROR] 打包未完成：", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
