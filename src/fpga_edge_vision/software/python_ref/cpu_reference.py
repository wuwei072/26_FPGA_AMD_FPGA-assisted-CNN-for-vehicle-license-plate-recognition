"""FPGA Edge Vision 的 CPU Sobel/ROI 参考模型（仅使用 Python 标准库）"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from collections import deque
from pathlib import Path
from typing import Sequence

# FPGA 固定配置
EDGE_PIXEL_THRESHOLD = 80
GRID_COLUMNS = 8
GRID_ROWS = 6
GRID_CELL_WIDTH = 80
GRID_CELL_HEIGHT = 80
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
# 网格采用 4 连通，对角接触不合并
GRID_CONNECTIVITY = 4
PIXEL_CONNECTIVITY = 8
GRID_EDGE_RATIO_THRESHOLD = 0.12
GX = ((-1, 0, 1), (-2, 0, 2), (-1, 0, 1))
GY = ((1, 2, 1), (0, 0, 0), (-1, -2, -1))
Image = list[list[int]]


def validate_image(image: Sequence[Sequence[int]]) -> tuple[int, int]:
    ### 检查图像为非空、矩形、8-bit 灰度数组，并返回宽高
    if not image or not image[0]:
        raise ValueError("image must not be empty")
    height, width = len(image), len(image[0])
    for row in image:
        if len(row) != width:
            raise ValueError("image rows must have equal width")
        if any(not isinstance(pixel, int) or not 0 <= pixel <= 255 for pixel in row):
            raise ValueError("pixels must be unsigned 8-bit integers")
    return width, height


def _read_p2(path: Path) -> Image:
    tokens = b"\n".join(line.split(b"#", 1)[0] for line in path.read_bytes().splitlines()).split()
    if len(tokens) < 4 or tokens[0] != b"P2":
        raise ValueError(f"invalid P2 PGM: {path}")
    width, height, maximum = map(int, tokens[1:4])
    pixels = [int(token) for token in tokens[4:]]
    if maximum != 255 or len(pixels) != width * height:
        raise ValueError(f"PGM must be 8-bit and complete: {path}")
    image = [pixels[y * width:(y + 1) * width] for y in range(height)]
    validate_image(image)
    return image


def _read_p5(path: Path) -> Image:
    content, index, header = path.read_bytes(), 0, []
    while len(header) < 4:
        while index < len(content) and content[index:index + 1].isspace():
            index += 1
        if index < len(content) and content[index:index + 1] == b"#":
            newline = content.find(b"\n", index)
            index = len(content) if newline == -1 else newline + 1
            continue
        end = index
        while end < len(content) and not content[end:end + 1].isspace():
            end += 1
        header.append(content[index:end])
        index = end
    if header[0] != b"P5":
        raise ValueError(f"invalid P5 PGM: {path}")
    width, height, maximum = map(int, header[1:4])
    if content[index:index + 2] == b"\r\n":
        index += 2
    elif index < len(content) and content[index:index + 1].isspace():
        index += 1
    else:
        raise ValueError(f"P5 header has no delimiter: {path}")
    pixels = list(content[index:])
    if maximum != 255 or len(pixels) != width * height:
        raise ValueError(f"PGM must be 8-bit and complete: {path}")
    image = [pixels[y * width:(y + 1) * width] for y in range(height)]
    validate_image(image)
    return image


def read_pgm(path: str | Path) -> Image:
    path = Path(path)
    magic = path.read_bytes()[:2]
    if magic == b"P2":
        return _read_p2(path)
    if magic == b"P5":
        return _read_p5(path)
    raise ValueError(f"only P2/P5 grayscale PGM is supported: {path}")


def write_pgm(path: str | Path, image: Sequence[Sequence[int]]) -> None:
    width, height = validate_image(image)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + bytes(p for row in image for p in row))


def sobel_edge(image: Sequence[Sequence[int]]) -> Image:
    width, height = validate_image(image)
    edge = [[0] * width for _ in range(height)]
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            gx = sum(GX[dy + 1][dx + 1] * image[y + dy][x + dx]
                     for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            gy = sum(GY[dy + 1][dx + 1] * image[y + dy][x + dx]
                     for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            edge[y][x] = min(255, abs(gx) + abs(gy))
    return edge


# FPGA 主线：8×6 网格级连通域
def effective_grid_shape(width: int, height: int, emit_warning: bool = True) -> tuple[int, int]:
    if width < 1 or height < 1:
        raise ValueError("image dimensions must be positive")
    columns, rows = min(GRID_COLUMNS, width), min(GRID_ROWS, height)
    if emit_warning and (columns != GRID_COLUMNS or rows != GRID_ROWS):
        warnings.warn(
            f"image is {width}x{height}; grid is automatically limited from "
            f"{GRID_COLUMNS}x{GRID_ROWS} to {columns}x{rows} to avoid empty cells",
            UserWarning,
            stacklevel=2,
        )
    return columns, rows


def binarize_edge(edge: Sequence[Sequence[int]]) -> Image:
    """阈值二值化"""
    validate_image(edge)
    return [[1 if value >= EDGE_PIXEL_THRESHOLD else 0 for value in row] for row in edge]


def _cell_bounds(index: int, total: int, grid: int) -> tuple[int, int]:
    return index * total // grid, (index + 1) * total // grid


def grid_edge_statistics(edge: Sequence[Sequence[int]]) -> list[dict[str, float | int]]:
    ## 统计 8×6 每个网格的边缘像素数与边缘密度
    width, height = validate_image(edge)
    columns, rows = effective_grid_shape(width, height)
    statistics: list[dict[str, float | int]] = []
    for row in range(rows):
        y0, y1 = _cell_bounds(row, height, rows)
        for col in range(columns):
            x0, x1 = _cell_bounds(col, width, columns)
            area = (x1 - x0) * (y1 - y0)
            count = sum(edge[y][x] >= EDGE_PIXEL_THRESHOLD
                        for y in range(y0, y1) for x in range(x0, x1)) if area else 0
            ratio = count / area if area else 0.0
            statistics.append({"grid_x": col, "grid_y": row, "x": x0, "y": y0,
                               "width": x1 - x0, "height": y1 - y0,
                               "edge_count": count, "edge_ratio": ratio,
                               "active": int(area > 0 and ratio > GRID_EDGE_RATIO_THRESHOLD)})
    return statistics


def active_grid_map(statistics: Sequence[dict[str, float | int]]) -> list[list[bool]]:
    if not statistics:
        raise ValueError("grid statistics must not be empty")
    rows = max(int(cell["grid_y"]) for cell in statistics) + 1
    columns = max(int(cell["grid_x"]) for cell in statistics) + 1
    if len(statistics) != rows * columns:
        raise ValueError("grid statistics must contain every cell exactly once")
    active = [[False] * columns for _ in range(rows)]
    for cell in statistics:
        active[int(cell["grid_y"])][int(cell["grid_x"])] = bool(cell["active"])
    return active


def _neighbors_4(x: int, y: int):
    return ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))


def grid_components(active: Sequence[Sequence[bool]]) -> list[dict[str, object]]:
    if not active or not active[0]:
        raise ValueError("active grid map must not be empty")
    rows, columns = len(active), len(active[0])
    if any(len(row) != columns for row in active):
        raise ValueError("active grid map must be rectangular")

    components: list[dict[str, object]] = []
    visited = [[False] * columns for _ in range(rows)]
    for start_y in range(rows):
        for start_x in range(columns):
            if not active[start_y][start_x] or visited[start_y][start_x]:
                continue
            queue, cells = deque([(start_x, start_y)]), []
            visited[start_y][start_x] = True
            while queue:
                x, y = queue.popleft()
                cells.append((x, y))
                for nx, ny in _neighbors_4(x, y):
                    if 0 <= nx < columns and 0 <= ny < rows and active[ny][nx] and not visited[ny][nx]:
                        visited[ny][nx] = True
                        queue.append((nx, ny))
            components.append({
                "grid_cells": sorted(cells, key=lambda cell: (cell[1], cell[0])),
                "grid_cell_count": len(cells),
                "grid_x_min": min(x for x, _ in cells),
                "grid_x_max": max(x for x, _ in cells),
                "grid_y_min": min(y for _, y in cells),
                "grid_y_max": max(y for _, y in cells),
            })
    return components


def grid_component_roi(component: dict[str, object], width: int, height: int) -> dict[str, int]:
    columns, rows = effective_grid_shape(width, height, emit_warning=False)
    x0, _ = _cell_bounds(int(component["grid_x_min"]), width, columns)
    x1, _ = _cell_bounds(int(component["grid_x_max"]) + 1, width, columns)
    y0, _ = _cell_bounds(int(component["grid_y_min"]), height, rows)
    y1, _ = _cell_bounds(int(component["grid_y_max"]) + 1, height, rows)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0,
            "grid_x": int(component["grid_x_min"]), "grid_y": int(component["grid_y_min"]),
            "grid_cell_count": int(component["grid_cell_count"])}


def grid_rois(edge: Sequence[Sequence[int]]) -> tuple[list[dict[str, float | int]], list[dict[str, int]]]:
    width, height = validate_image(edge)
    statistics = grid_edge_statistics(edge)
    active = active_grid_map(statistics)
    rois = [grid_component_roi(component, width, height) for component in grid_components(active)]
    return statistics, rois


def select_largest_grid_component(components: Sequence[dict[str, int]]) -> dict[str, int] | None:
    if not components:
        return None
    component = min(components, key=lambda item: (-item["grid_cell_count"], item["grid_y"], item["grid_x"]))
    return {key: component[key] for key in ("x", "y", "width", "height", "grid_cell_count")}


def fpga_mainline_roi(edge: Sequence[Sequence[int]]) -> tuple[list[dict[str, float | int]], list[dict[str, int]], dict[str, int] | None]:
    statistics, components = grid_rois(edge)
    return statistics, components, select_largest_grid_component(components)

# 软件对照：像素级连通域
def pixel_edge_components(edge: Sequence[Sequence[int]], connectivity: int = PIXEL_CONNECTIVITY) -> list[dict[str, object]]:
    width, height = validate_image(edge)
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    offsets = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)) \
        if connectivity == 8 else _neighbors_4(0, 0)

    edge_pixels = {(x, y) for y in range(height) for x in range(width)
                   if edge[y][x] >= EDGE_PIXEL_THRESHOLD}
    remaining = set(edge_pixels)
    components: list[dict[str, object]] = []
    for seed in sorted(edge_pixels, key=lambda pixel: (pixel[1], pixel[0])):
        if seed not in remaining:
            continue
        remaining.discard(seed)
        queue, pixels = deque([seed]), []
        min_x = max_x = seed[0]
        min_y = max_y = seed[1]
        while queue:
            x, y = queue.popleft()
            pixels.append((x, y))
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for dx, dy in offsets:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) in remaining:
                    remaining.discard((nx, ny))
                    queue.append((nx, ny))
        components.append({
            "pixel_count": len(pixels),
            "x": min_x, "y": min_y,
            "width": max_x - min_x + 1, "height": max_y - min_y + 1,
            "bbox_area": (max_x - min_x + 1) * (max_y - min_y + 1),
        })
    return components


def select_largest_pixel_component(components: Sequence[dict[str, object]],
                                   by: str = "pixel_count") -> dict[str, object] | None:
    if not components:
        return None
    if by not in ("pixel_count", "bbox_area"):
        raise ValueError("by must be 'pixel_count' or 'bbox_area'")
    chosen = min(components, key=lambda item: (-int(item[by]), int(item["y"]), int(item["x"])))
    return dict(chosen)


def pixel_reference_roi(edge: Sequence[Sequence[int]],
                        by: str = "pixel_count") -> dict[str, object] | None:
    return select_largest_pixel_component(pixel_edge_components(edge), by=by)


def annotate_rois(image: Sequence[Sequence[int]], rois: Sequence[dict[str, int]]) -> Image:
    width, height = validate_image(image)
    result = [list(row) for row in image]
    for roi in rois:
        if roi["width"] <= 0 or roi["height"] <= 0:
            continue
        x0, y0 = roi["x"], roi["y"]
        x1, y1 = x0 + roi["width"] - 1, y0 + roi["height"] - 1
        if not (0 <= x0 <= x1 < width and 0 <= y0 <= y1 < height):
            raise ValueError("ROI is outside image bounds")
        for x in range(x0, x1 + 1):
            result[y0][x] = result[y1][x] = 255
        for y in range(y0, y1 + 1):
            result[y][x0] = result[y][x1] = 255
    return result


def _synthetic_images() -> dict[str, Image]:
    """生成固定、可复现的几何、噪声和多目标合成测试图"""
    width, height = 640, 480
    geometry = [[20] * width for _ in range(height)]
    for y in range(100, 350):
        for x in range(90, 290):
            geometry[y][x] = 220
    for y in range(height):
        for x in range(width):
            if (x - 460) ** 2 + (y - 230) ** 2 <= 90 ** 2:
                geometry[y][x] = 160
    noise = [[(x * 17 + y * 31 + 19) % 64 + 96 for x in range(width)] for y in range(height)]
    for y in range(150, 330):
        for x in range(210, 430):
            noise[y][x] = min(255, noise[y][x] + 110)
    targets = [[15] * width for _ in range(height)]
    for x0, y0, x1, y1, value in ((50, 60, 170, 175, 230), (350, 90, 565, 210, 180), (240, 300, 430, 430, 255)):
        for y in range(y0, y1):
            for x in range(x0, x1):
                targets[y][x] = value
    return {"synthetic_geometry": geometry, "synthetic_noise": noise, "synthetic_multi_target": targets}


def _fill_stripes(image: Image, x0: int, y0: int, width: int, height: int) -> None:
    for y in range(y0, y0 + height):
        for x in range(x0, x0 + width):
            image[y][x] = 32 if (x - x0) // 2 % 2 == 0 else 224


def golden_vector_images() -> dict[str, Image]:
    """构造可重复的冻结向量：小图、单目标、多目标和带噪声目标"""
    width, height = 640, 480
    single = [[16] * width for _ in range(height)]
    _fill_stripes(single, 160, 160, 160, 160)
    multi = [[16] * width for _ in range(height)]
    _fill_stripes(multi, 80, 80, 240, 160)
    _fill_stripes(multi, 400, 320, 80, 80)
    noise = [[40 + (x * 17 + y * 31 + 19) % 8 for x in range(width)] for y in range(height)]
    _fill_stripes(noise, 400, 160, 160, 160)
    small = [[0, 0, 255, 255, 255] for _ in range(5)]
    return {"small_5x5": small, "single_target_640x480": single,
            "multi_target_640x480": multi, "noise_target_640x480": noise}


def roi_reduction_ratio(roi: dict[str, int] | None, width: int, height: int) -> float:
    if not roi or roi["width"] <= 0 or roi["height"] <= 0:
        return 1.0
    return 1.0 - (roi["width"] * roi["height"]) / (width * height)


def roi_json_record(roi: dict[str, int] | None) -> dict[str, int]:
    if roi is None:
        return {"roi_valid": 0, "roi_x": 0, "roi_y": 0, "roi_width": 0,
                "roi_height": 0, "roi_grid_cell_count": 0}
    return {"roi_valid": 1, "roi_x": roi["x"], "roi_y": roi["y"],
            "roi_width": roi["width"], "roi_height": roi["height"],
            "roi_grid_cell_count": roi["grid_cell_count"]}


def write_golden_vectors(golden_root: str | Path,
                         write_edge_artifacts: bool = True) -> list[dict]:
    directory = Path(golden_root)
    directory.mkdir(parents=True, exist_ok=True)
    summaries = []
    for name, source in golden_vector_images().items():
        edge = sobel_edge(source)
        statistics, components, largest = fpga_mainline_roi(edge)
        # components 仅含 ROI 字段，此处另取原始网格成员
        raw_components = grid_components(active_grid_map(statistics))
        width, height = validate_image(source)
        columns, rows = effective_grid_shape(width, height, emit_warning=False)

        pixel_components = pixel_edge_components(edge, connectivity=PIXEL_CONNECTIVITY)
        pixel_largest = select_largest_pixel_component(pixel_components, by="pixel_count")

        roi_json = roi_json_record(largest)
        summary = {
            "name": name,
            "width": width,
            "height": height,
            "grid_columns": columns,
            "grid_rows": rows,
            "grid_cell_count": columns * rows,
            "requested_grid_columns": GRID_COLUMNS,
            "requested_grid_rows": GRID_ROWS,
            "requested_grid_cell_width": GRID_CELL_WIDTH,
            "requested_grid_cell_height": GRID_CELL_HEIGHT,
            "grid_connectivity": GRID_CONNECTIVITY,
            "edge_pixel_threshold": EDGE_PIXEL_THRESHOLD,
            "grid_edge_ratio_threshold": GRID_EDGE_RATIO_THRESHOLD,
            "connected_region_count": len(components),
            "grid_statistics": statistics,
            "all_grid_components": [
                {"grid_cells": [list(cell) for cell in component["grid_cells"]],
                 "grid_cell_count": component["grid_cell_count"],
                 "grid_x_min": component["grid_x_min"], "grid_x_max": component["grid_x_max"],
                 "grid_y_min": component["grid_y_min"], "grid_y_max": component["grid_y_max"]}
                for component in raw_components
            ],
            "all_grid_component_rois": components,
            "largest_grid_component_roi": roi_json,
            "roi_data_reduction_ratio": roi_reduction_ratio(largest, width, height),
            # 以下字段属于软件对照
            "pixel_reference_connectivity": PIXEL_CONNECTIVITY,
            "pixel_reference_component_count": len(pixel_components),
            "pixel_reference_largest_roi": pixel_largest,
        }
        if write_edge_artifacts:
            write_pgm(directory / f"{name}_input.pgm", source)
            write_pgm(directory / f"{name}_edge.pgm", edge)
        (directory / f"{name}_roi.json").write_text(json.dumps(roi_json, indent=2) + "\n", encoding="utf-8")
        (directory / f"{name}_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        summaries.append(summary)
    return summaries


def discover_or_generate(data_root: Path) -> list[Path]:
    """只读取 data/input；目录无图时生成三张 640×480 合成图"""
    input_dir = data_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(path for path in input_dir.glob("*.pgm") if path.is_file())
    if images:
        return images
    for name, image in _synthetic_images().items():
        write_pgm(input_dir / f"{name}.pgm", image)
    return sorted(input_dir.glob("*.pgm"))


def run_pipeline(data_root: str | Path, results_root: str | Path) -> list[dict]:
    """处理输入图并输出原图、边缘图、ROI 标注图及可复核 JSON"""
    result_dir = Path(results_root)
    result_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for image_path in discover_or_generate(Path(data_root)):
        started = time.perf_counter()
        source = read_pgm(image_path)
        edge = sobel_edge(source)
        statistics, components, largest_roi = fpga_mainline_roi(edge)
        output_rois = [largest_roi] if largest_roi else []
        annotated = annotate_rois(source, output_rois)
        width, height = validate_image(source)
        prefix = image_path.stem
        write_pgm(result_dir / f"{prefix}_original.pgm", source)
        write_pgm(result_dir / f"{prefix}_edge.pgm", edge)
        write_pgm(result_dir / f"{prefix}_roi.pgm", annotated)
        kept_pixels = sum(roi["width"] * roi["height"] for roi in output_rois)
        # 网格统计阶段已给出过小图限幅警告，此处仅记录实际配置
        effective_columns, effective_rows = effective_grid_shape(width, height, emit_warning=False)
        summary = {"input": str(image_path), "width": width, "height": height,
                   "requested_grid_columns": GRID_COLUMNS, "requested_grid_rows": GRID_ROWS,
                   "grid_columns": effective_columns, "grid_rows": effective_rows,
                   "edge_pixel_threshold": EDGE_PIXEL_THRESHOLD,
                   "grid_edge_ratio_threshold": GRID_EDGE_RATIO_THRESHOLD,
                   "grid_connectivity": GRID_CONNECTIVITY,
                   "connected_region_count": len(components),
                   "all_grid_components": components, "largest_grid_component_roi": largest_roi,
                   "roi_pixels": kept_pixels,
                   "roi_data_reduction_ratio": roi_reduction_ratio(largest_roi, width, height),
                   "elapsed_ms": (time.perf_counter() - started) * 1000,
                   "grid_statistics": statistics}
        (result_dir / f"{prefix}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summaries.append(summary)
    (result_dir / "run_summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return summaries


def main() -> None:
    root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description="FPGA Edge Vision CPU reference model")
    parser.add_argument("--data", type=Path, default=root / "data")
    parser.add_argument("--results", type=Path, default=root / "data" / "reference_results")
    parser.add_argument("--write-golden-vectors", action="store_true")
    args = parser.parse_args()
    if args.write_golden_vectors:
        vectors = write_golden_vectors(root / "data" / "golden_vectors")
        print(f"Wrote {len(vectors)} reproducible golden vectors.")
        return
    for item in run_pipeline(args.data, args.results):
        print(f"{Path(item['input']).name}: {item['elapsed_ms']:.3f} ms, "
              f"ROI reduction {item['roi_data_reduction_ratio']:.2%}, "
              f"grid regions {item['connected_region_count']}")


if __name__ == "__main__":
    main()
