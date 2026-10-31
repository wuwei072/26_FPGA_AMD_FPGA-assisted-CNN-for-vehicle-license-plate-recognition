# FPGA Edge Vision FPGA Interface Specification

## Status and Scope

This document freezes the FPGA-functional baseline. It specifies behavior only; it does not define a Vivado project, PYNQ application, DMA path, HLS implementation, clock frequency, or register map.

## Fixed Processing Flow

`8-bit grayscale input -> 3x3 Sobel -> threshold binarization -> 8x6 grid edge-density count -> active-grid decision -> 4-connected grid-region merge -> largest region ROI output`

Only the final, largest grid-connected region is the FPGA mainline ROI. All grid-connected regions may be retained by Python only as diagnostic data.

## Frame Input

| Item | Fixed value |
| --- | --- |
| Frame width | 640 pixels |
| Frame height | 480 pixels |
| Pixel format | Unsigned 8-bit grayscale, range 0 to 255 |
| Scan order | Row-major: left to right, then top to bottom |
| Pixels per frame | 307200 |

## Sobel and Binary Edge Rule

`Gx = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]`

`Gy = [[1, 2, 1], [0, 0, 0], [-1, -2, -1]]`

For every non-border pixel, calculate `M = min(255, abs(Gx) + abs(Gy))`. All pixels in the first/last row or first/last column must output `M = 0`.

The binary edge flag is `1` when `M >= 80`; otherwise it is `0`. The `>=` comparison is fixed.

## Grid and Active Decision

The frame is divided into 8 columns by 6 rows. Every grid cell is exactly 80 by 80 pixels, with 6400 pixels per cell.

For each cell, count binary edge flags as `edge_count`. A cell is active only when:

`edge_count / 6400 > 0.12`

Equivalently, `edge_count > 768`. Equality (`edge_count = 768`) is inactive.

## Grid Connectivity and Largest Region

- Connectivity is fixed to 4-connectivity: up, down, left, and right only.
- Diagonal contact does not connect two active cells.
- Merge each connected active-cell set into one region.
- Choose the region with the largest number of grid cells.
- If two regions have the same cell count, choose the region with smaller `grid_y`; if still tied, choose smaller `grid_x`.

The selected region's ROI is the bounding rectangle of its grid cells. If no cell is active, `roi_valid` is zero and ROI coordinates/sizes are zero.

## ROI Output Format

| Field | Width | Meaning |
| --- | --- | --- |
| `roi_valid` | 1 | `1` when a largest region exists; otherwise `0`. |
| `roi_x` | 16 | Inclusive pixel x coordinate of ROI top-left. |
| `roi_y` | 16 | Inclusive pixel y coordinate of ROI top-left. |
| `roi_width` | 16 | ROI width in pixels. |
| `roi_height` | 16 | ROI height in pixels. |
| `roi_grid_cell_count` | 6 | Number of active cells in the selected region, range 1 to 48. |

For a valid ROI, `0 <= roi_x < 640`, `0 <= roi_y < 480`, `roi_x + roi_width <= 640`, and `roi_y + roi_height <= 480`.

## ROI Data Reduction

The selected ROI payload is `roi_width * roi_height` grayscale bytes. The reduction relative to a complete 640x480 frame is:

`roi_data_reduction_ratio = 1 - (roi_width * roi_height) / (640 * 480)`

When `roi_valid = 0`, selected payload is zero and the reduction ratio is `1.0`.

## Python-to-FPGA Acceptance Criteria

For every vector in `data/golden_vectors/`, compare Python and FPGA results in this order:

1. Input frame dimensions and every unsigned 8-bit input pixel must match exactly.
2. Every Sobel output pixel, including the zero border, must match exactly.
3. Every binary edge flag must match exactly using `M >= 80`.
4. All 48 per-grid `edge_count` values must match exactly; their active flags must also match exactly.
5. The number and membership of 4-connected grid regions must match exactly.
6. `roi_valid`, `roi_x`, `roi_y`, `roi_width`, `roi_height`, and `roi_grid_cell_count` for the selected largest region must match exactly.
7. The ROI data-reduction ratio must equal the specified formula; compare the numerator (`roi_width * roi_height`) exactly rather than relying on floating-point rounding.

Pipeline latency is allowed, but it must not change any frame-positioned output or final ROI result.
