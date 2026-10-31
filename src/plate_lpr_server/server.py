"""PYNQ 车牌识别服务。"""
import os
import re
import sys
import tempfile
import time
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if Path(sys.prefix).resolve() != ROOT / "venv":
    raise RuntimeError("请使用本目录虚拟环境运行")

TMP_DIR = ROOT / ".tmp"
TMP_DIR.mkdir(exist_ok=True)
tempfile.tempdir = str(TMP_DIR)

import cv2
import numpy as np
from flask import Flask, abort, jsonify, request
from waitress import serve
from werkzeug.exceptions import HTTPException


def load_model():
    package = distribution("hyperlpr3")
    source = Path(package.locate_file("hyperlpr3/hyperlpr3.py")).read_text(encoding="utf-8")
    if (
        "# LOCAL_ONLY: automatic model download disabled" not in source
        or re.search(r"(?m)^initialization\(\)[ \t]*$", source)
    ):
        raise RuntimeError("请先运行 prepare_models.py，禁用模型自动下载")

    import onnxruntime as ort
    ort.disable_telemetry_events()
    from hyperlpr3 import LicensePlateCatcher
    return LicensePlateCatcher(folder=str(ROOT / "models"), detect_level=0, logger_level=3)


MIN_RECOGNITION_CONFIDENCE = 0.90
PLATE_PATTERN = re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z][A-HJ-NP-Z0-9]{5,6}")
AUTO_SAVE_POLICY = "plate-confirmed-v2"

MODEL = load_model()
print("[System] 车牌模型已加载", flush=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
app.json.ensure_ascii = False


@app.get("/health")
def health():
    return jsonify({"status": "ok", "auto_save_policy": AUTO_SAVE_POLICY})


@app.errorhandler(Exception)
def request_error(error):
    app.logger.error("%s", error)
    return jsonify({"status": "fail"}), error.code if isinstance(error, HTTPException) else 500


@app.post("/api/recognize")
def api_recognize():
    data = np.frombuffer(request.get_data(cache=False), dtype=np.uint8)
    if not data.size:
        abort(400)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        abort(400)

    start = time.perf_counter()
    candidates = []
    for result in MODEL(image):
        plate = result[0].strip().upper()
        confidence = float(result[1])
        if MIN_RECOGNITION_CONFIDENCE <= confidence <= 1.0 and PLATE_PATTERN.fullmatch(plate):
            candidates.append((plate, confidence))
    if not candidates:
        return jsonify({"status": "fail"})
    plate, confidence = max(candidates, key=lambda item: item[1])
    elapsed_ms = (time.perf_counter() - start) * 1000
    return jsonify({"status": "success", "plate": plate, "confidence": round(confidence, 4),
                    "auto_save_allowed": True, "time_ms": round(elapsed_ms, 2)})


if __name__ == "__main__":
    pid_path = ROOT / "server.pid"
    pid_path.write_text(str(os.getpid()), encoding="ascii")
    print("[System] PYNQ 接口：http://笔记本IPv4:5000/api/recognize", flush=True)
    print("[System] 按 Ctrl+C 停止服务", flush=True)
    try:
        serve(app, host="0.0.0.0", port=5000, threads=1,
              max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
    finally:
        if pid_path.is_file() and pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
            pid_path.unlink()
