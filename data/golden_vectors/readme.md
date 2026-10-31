# Golden Vectors

These deterministic PGM/JSON vectors freeze the FPGA functional baseline.

| Vector | Purpose | Expected largest ROI |
| --- | --- | --- |
| `small_5x5` | Border and reduced-grid behavior | `x=1, y=1, width=2, height=3` |
| `single_target_640x480` | One 2x2 active-grid target | `x=160, y=160, width=160, height=160` |
| `multi_target_640x480` | A 6-cell target versus a 1-cell target | `x=80, y=80, width=240, height=160` |
| `noise_target_640x480` | Deterministic low-amplitude noise plus one target | `x=400, y=160, width=160, height=160` |

Each vector has `_input.pgm`, `_edge.pgm`, `_roi.json`, and `_summary.json` artifacts. `PGM` is 8-bit grayscale P5 data. The JSON summary records the fixed threshold, grid shape, selected ROI, and reduction ratio.

To recreate the artifacts from the reference model in an available Python environment:

```powershell
python software/python_ref/cpu_reference.py --write-golden-vectors
```
