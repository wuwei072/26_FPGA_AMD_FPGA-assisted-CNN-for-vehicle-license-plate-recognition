"""
生成 HDL 仿真用的 raw .bin 向量
把 data/golden_vectors/ 里的 P5 PGM（带 15 字节头部）剥成**纯像素流**，
供 SystemVerilog testbench 用 $fread 直接读入。

输出（每个向量的输入图和期望边缘图各一个）：
    hardware/sim/vectors/<name>_input.bin     307200 字节
    hardware/sim/vectors/<name>_expected.bin  307200 字节
    字节序：行优先，1 字节 1 像素，无头部
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "data" / "golden_vectors"
OUT_DIR = REPO_ROOT / "hardware" / "sim" / "vectors"

WIDTH = 640
HEIGHT = 480
NPIX = WIDTH * HEIGHT

# DUT 固定 640x480
VECTORS = ["single_target_640x480", "multi_target_640x480", "noise_target_640x480"]


def read_pgm_pixels(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] not in (b"P2", b"P5"):
        raise ValueError("%s 不是 P2/P5 PGM" % path)

    binary = data[1:2] == b"5"
    idx = 2
    tokens: list[bytes] = []
    while len(tokens) < 3:
        while idx < len(data) and data[idx:idx + 1].isspace():
            idx += 1
        if data[idx:idx + 1] == b"#":
            idx = data.find(b"\n", idx) + 1
            continue
        end = idx
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        tokens.append(data[idx:end])
        idx = end

    w, h, maxval = (int(t) for t in tokens)
    if maxval != 255:
        raise ValueError("%s 的 maxval=%d，只支持 255" % (path, maxval))
    if w != WIDTH or h != HEIGHT:
        raise ValueError("%s 尺寸为 %dx%d，DUT 只支持 %dx%d"
                         % (path, w, h, WIDTH, HEIGHT))

    if binary:
        if data[idx:idx + 2] == b"\r\n":
            idx += 2
        elif data[idx:idx + 1].isspace():
            idx += 1
        pixels = data[idx:]
    else:
        toks = data[idx:].split()
        pixels = bytes(int(t) for t in toks)

    if len(pixels) != NPIX:
        raise ValueError("%s 像素数 %d != %d" % (path, len(pixels), NPIX))
    return pixels


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("生成 HDL 仿真向量（raw .bin）")
    print("  源目录：%s" % GOLDEN_DIR)
    print("  输出  ：%s" % OUT_DIR)
    print("=" * 88)

    created = []
    for name in VECTORS:
        src_in = GOLDEN_DIR / ("%s_input.pgm" % name)
        src_ex = GOLDEN_DIR / ("%s_edge.pgm" % name)
        if not src_in.is_file() or not src_ex.is_file():
            print("  跳过 %s：找不到输入或期望边缘图" % name)
            continue

        pin = read_pgm_pixels(src_in)
        pex = read_pgm_pixels(src_ex)

        dst_in = OUT_DIR / ("%s_input.bin" % name)
        dst_ex = OUT_DIR / ("%s_expected.bin" % name)
        dst_in.write_bytes(pin)
        dst_ex.write_bytes(pex)

        created += [dst_in, dst_ex]
        print("  %-24s input=%d 字节  expected=%d 字节"
              % (name, len(pin), len(pex)))

    print()
    print("新建文件（%d 个）：" % len(created))
    for p in created:
        print("   +", p.relative_to(REPO_ROOT))
    print()
    print("期望每个文件大小 = %d 字节（= 640*480，行优先，无头部）" % NPIX)
    return 0


if __name__ == "__main__":
    sys.exit(main())
