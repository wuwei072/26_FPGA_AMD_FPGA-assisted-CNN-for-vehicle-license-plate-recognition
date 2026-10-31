"""三组Golden向量验证：真实FPGA边缘图 + ROI六字段"""

from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
if ROOT.name == "validation":
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from edge_dma_runtime import EdgeDmaRuntime, WIDTH, HEIGHT, FRAME_BYTES


VECTOR_DIR = ROOT / "validation"
CASES = [
    ("single_target", [160, 160, 160, 160, 4, 9167]),
    ("multi_target", [80, 80, 240, 160, 6, 8750]),
    ("noise_target", [400, 160, 160, 160, 4, 9167]),
]


def load_bin(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size != FRAME_BYTES:
        raise ValueError("{}包含{}字节，应为{}".format(path, data.size, FRAME_BYTES))
    return data.reshape(HEIGHT, WIDTH)


def main():
    print("=== FPGA EDGE + ROI GOLDEN VALIDATION ===")
    runtime = EdgeDmaRuntime(ROOT)
    all_ok = True
    try:
        for stem, expected_roi in CASES:
            input_path = VECTOR_DIR / (stem + "_640x480_input.bin")
            edge_path = VECTOR_DIR / (stem + "_640x480_expected.bin")
            gray = load_bin(input_path)
            # Golden文件保存饱和后的Sobel幅值；硬件回传的是阈值80的二值图
            expected_magnitude = load_bin(edge_path)
            expected_edge = np.where(expected_magnitude >= 80, 255, 0).astype(np.uint8)

            got_roi, got_edge, dma_ms = runtime.run_gray(gray)
            edge_mismatches = int(np.count_nonzero(got_edge != expected_edge))
            border_nonzero = int(
                np.count_nonzero(got_edge[0, :])
                + np.count_nonzero(got_edge[-1, :])
                + np.count_nonzero(got_edge[1:-1, 0])
                + np.count_nonzero(got_edge[1:-1, -1])
            )
            ok = (
                got_roi == expected_roi
                and edge_mismatches == 0
                and border_nonzero == 0
            )
            all_ok = all_ok and ok
            print("\n{}".format(stem))
            print("  ROI got/expected = {} / {}".format(got_roi, expected_roi))
            print("  edge mismatches  = {}".format(edge_mismatches))
            print("  border nonzero   = {}".format(border_nonzero))
            print("  DMA elapsed      = {:.3f} ms".format(dma_ms))
            print("  {}".format("PASS" if ok else "FAIL"))

        print("\nALL PASS" if all_ok else "\nSOME FAILED - STOP BEFORE CAMERA DEMO")
        if not all_ok:
            raise AssertionError("边缘图或ROI与Golden不一致")
    finally:
        runtime.close()


if __name__ == "__main__":
    main()

