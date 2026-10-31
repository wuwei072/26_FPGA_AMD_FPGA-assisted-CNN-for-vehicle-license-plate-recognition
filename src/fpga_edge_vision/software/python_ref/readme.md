# CPU Reference Model

This directory contains the Phase 1 CPU reference model only. It uses Python's standard library and supports 8-bit grayscale PGM (`P2` or `P5`) input, so it has no mandatory package dependency.

## Run

From the repository root, run:

```powershell
python software/python_ref/cpu_reference.py
python -m unittest software/python_ref/test_cpu_reference.py -v
python software/python_ref/cpu_reference.py --write-golden-vectors
```

The program reads `.pgm` input images under `data/` and excludes `data/expected/` golden outputs. It also ensures that three deterministic 640×480 synthetic images exist in `data/input/`: `synthetic_geometry.pgm`, `synthetic_noise.pgm`, and `synthetic_multi_target.pgm`. Outputs are written to `results/python_ref/` as original, edge, ROI-annotated PGM images and JSON summaries.

## Fixed FPGA Contract

- Input: 8-bit single-channel PGM pixels, row-major, left-to-right and top-to-bottom.
- Sobel: `abs(Gx) + abs(Gy)`, saturated to 255; the outer one-pixel border is zero.
- Grid: 8 columns by 6 rows. A 640×480 frame therefore has exactly 80×80 pixels per grid cell. For smaller images, the model clearly warns and limits each grid dimension to the corresponding image dimension, so no empty grid cell can exist.
- Edge pixel threshold: 80; active-grid ratio threshold: strictly greater than 0.12.
- ROI: four-neighbor connected active grid cells are merged; ROI coordinates are `x`, `y`, `width`, and `height`.

Future FPGA output must follow this contract exactly, except for pipeline latency.

`--write-golden-vectors` recreates the frozen vectors in `data/golden_vectors/`.
