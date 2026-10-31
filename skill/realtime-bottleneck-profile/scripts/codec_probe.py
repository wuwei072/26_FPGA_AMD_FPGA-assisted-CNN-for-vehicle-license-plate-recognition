"""真实图像编码实验；需在已有的 OpenCV / NumPy 环境中运行。"""
import argparse
import math
from pathlib import Path
import statistics
import time


def measure(image, extension, options, repeats, cv2):
    ok, _ = cv2.imencode(extension, image, options)
    if not ok:
        raise RuntimeError("编码预热失败")
    times, sizes = [], []
    for _ in range(repeats):
        start = time.perf_counter()
        ok, encoded = cv2.imencode(extension, image, options)
        elapsed = (time.perf_counter() - start) * 1000
        if not ok:
            raise RuntimeError("编码失败")
        times.append(elapsed)
        sizes.append(encoded.size)
    return encoded, dict(mean_ms=statistics.mean(times),
                         p95_ms=sorted(times)[math.ceil(.95 * len(times)) - 1],
                         bytes=statistics.mean(sizes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat 必须大于 0")
    import cv2
    import numpy as np
    # fromfile/imdecode 兼容含中文的文件路径。
    color = cv2.imdecode(np.fromfile(str(args.color), np.uint8), cv2.IMREAD_COLOR)
    edge = cv2.imdecode(np.fromfile(str(args.binary), np.uint8), cv2.IMREAD_UNCHANGED)
    if color is None or edge is None:
        parser.error("无法解码输入文件")
    if edge.dtype != np.uint8 or edge.ndim != 2 or cv2.countNonZero(cv2.inRange(edge, 1, 254)):
        parser.error("binary 必须是原生单通道 uint8，且仅包含 0/255；禁止偷偷转换")
    if not hasattr(cv2, "IMWRITE_PNG_BILEVEL"):
        parser.error("此 OpenCV 不支持 IMWRITE_PNG_BILEVEL")
    print(f"OpenCV {cv2.__version__}; color={color.shape}; binary={edge.shape}; repeat={args.repeat}")
    configs = [("JPEG", color, ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 60]),
               ("PNG-8", edge, ".png", [cv2.IMWRITE_PNG_COMPRESSION, 1]),
               ("PNG-1", edge, ".png", [cv2.IMWRITE_PNG_COMPRESSION, 1, cv2.IMWRITE_PNG_BILEVEL, 1])]
    for name, image, ext, options in configs:
        encoded, result = measure(image, ext, options, args.repeat, cv2)
        print(name, result)
        if ext == ".png":
            restored = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
            exact = np.array_equal(restored, edge)
            depth = int(encoded[24])  # PNG signature + IHDR: bit depth byte
            print("  bit_depth=", depth, "lossless_match=", exact)
            if not exact or depth != (1 if name == "PNG-1" else 8):
                raise RuntimeError("PNG 位深或无损一致性未通过，不采用此配置")
    print("读盘、二值检查、解码核验不在编码计时内；JPEG 不宣称无损。")


if __name__ == "__main__":
    main()
