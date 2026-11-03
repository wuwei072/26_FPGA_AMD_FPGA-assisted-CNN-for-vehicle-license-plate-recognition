from __future__ import annotations

from pathlib import Path

GRID_COLUMNS = 8
GRID_ROWS = 6
GRID_COUNT = GRID_COLUMNS * GRID_ROWS
GRID_CELL_SIZE = 80
ACTIVE_THRESHOLD = 768

# Python 整数没有固定宽度，所有位图运算都限制为 48 bit
BITMAP_MASK = (1 << GRID_COUNT) - 1

# 每个字节表示一行网格；bit0/bit7 分别是该行的第0/7列
COL0_MASK = 0x010101010101
COL7_MASK = 0x808080808080

def load_grid_counts_hex(path: str | Path) -> list[int]:
    source = Path(path)
    counts: list[int] = []

    try:
        lines = source.read_text(encoding="ascii").splitlines()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"grid-count vector not found: {source}") from exc

    for line_number, line in enumerate(lines, start=1):
        token = line.strip()
        if not token:
            continue
        if len(token) != 4:
            raise ValueError(f"{source}:{line_number}: expected exactly four hexadecimal digits")
        try:
            value = int(token, 16)
        except ValueError as exc:
            raise ValueError(f"{source}:{line_number}: invalid hexadecimal count {token!r}") from exc
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"{source}:{line_number}: count is outside 16-bit range")
        counts.append(value)

    if len(counts) != GRID_COUNT:
        raise ValueError(f"{source}: expected {GRID_COUNT} counts, found {len(counts)}")
    return counts


def _validate_grid_counts(grid_counts: list[int]) -> None:
    if not isinstance(grid_counts, list):
        raise TypeError("grid_counts must be a list")
    if len(grid_counts) != GRID_COUNT:
        raise ValueError(f"grid_counts must contain exactly {GRID_COUNT} values")
    for index, value in enumerate(grid_counts):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"grid_counts[{index}] must be an integer")
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"grid_counts[{index}]={value} is outside unsigned 16-bit range" )


def _reduction_x100(bbox_grid_count: int) -> int:
   
    
    numerator = (GRID_COUNT - bbox_grid_count) * 10000
    return (numerator + GRID_COUNT // 2) // GRID_COUNT


def roi_engine_reference(grid_counts: list[int]) -> dict:
    _validate_grid_counts(grid_counts)

    # count > 768 是活跃网格
    active_map = 0
    for grid_index, count in enumerate(grid_counts):
        if count > ACTIVE_THRESHOLD:
            active_map |= 1 << grid_index
    active_map &= BITMAP_MASK

    unvisited_map = active_map
    best_size = 0
    best_bbox: tuple[int, int, int, int] | None = None

    # 每轮从最低置位 bit 开始，区域发现顺序从上到下、从左到右
    while unvisited_map != 0:
        seed_bit = unvisited_map & -unvisited_map
        seed_index = seed_bit.bit_length() - 1
        seed_x = seed_index % GRID_COLUMNS
        seed_y = seed_index // GRID_COLUMNS

        component_map = 0
        frontier_map = 1 << seed_index
        component_size = 0
        comp_min_x = comp_max_x = seed_x
        comp_min_y = comp_max_y = seed_y

        # 一次循环等价 RTL 一拍 EXPAND_ITER：同时扩张当前整层前沿
        while frontier_map != 0:
            neighbor_map = ( (frontier_map >> GRID_COLUMNS) | (frontier_map << GRID_COLUMNS) | ((frontier_map >> 1) & ~COL7_MASK) | ((frontier_map << 1) & ~COL0_MASK) ) & BITMAP_MASK

            # 只保留活跃且尚未进入组件/当前前沿的网格
            new_frontier = (neighbor_map & active_map & (~(component_map | frontier_map) & BITMAP_MASK) )

            component_map |= frontier_map
            component_size += bin(frontier_map).count("1")

            # 逐个扫描当前前沿置位 bit，更新该连通区域的网格包围框
            frontier_bits = frontier_map
            while frontier_bits != 0:
                bit = frontier_bits & -frontier_bits
                bit_index = bit.bit_length() - 1
                grid_x = bit_index % GRID_COLUMNS
                grid_y = bit_index // GRID_COLUMNS
                comp_min_x = min(comp_min_x, grid_x)
                comp_max_x = max(comp_max_x, grid_x)
                comp_min_y = min(comp_min_y, grid_y)
                comp_max_y = max(comp_max_y, grid_y)
                frontier_bits &= frontier_bits - 1

            frontier_map = new_frontier

        # RTL 仅在严格更大时替换
        if component_size > best_size:
            best_size = component_size
            best_bbox = (comp_min_x, comp_max_x, comp_min_y, comp_max_y)

        unvisited_map &= ~component_map
        unvisited_map &= BITMAP_MASK

    if best_size == 0 or best_bbox is None:
        return {
            "roi_x": 0,
            "roi_y": 0,
            "roi_w": 0,
            "roi_h": 0,
            "best_grids": 0,
            "reduction_x100": 10000,
        }

    best_min_x, best_max_x, best_min_y, best_max_y = best_bbox
    bbox_width = best_max_x - best_min_x + 1
    bbox_height = best_max_y - best_min_y + 1
    bbox_grid_count = bbox_width * bbox_height

    return {
        "roi_x": best_min_x * GRID_CELL_SIZE,
        "roi_y": best_min_y * GRID_CELL_SIZE,
        "roi_w": bbox_width * GRID_CELL_SIZE,
        "roi_h": bbox_height * GRID_CELL_SIZE,
        "best_grids": best_size,
        "reduction_x100": _reduction_x100(bbox_grid_count),
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[4]
    vector_root = project_root / "data" / "hdl_vectors"
    vector_names = (
        "single_target_640x480",
        "multi_target_640x480",
        "noise_target_640x480",
    )

    for name in vector_names:
        vector_path = vector_root / f"{name}_grid_counts.hex"
        result = roi_engine_reference(load_grid_counts_hex(vector_path))
        print(
            f"{name}: "
            f"ROI=({result['roi_x']},{result['roi_y']},"
            f"{result['roi_w']},{result['roi_h']}), "
            f"best_grids={result['best_grids']}, "
            f"reduction={result['reduction_x100'] / 100:.2f}% "
            f"(reduction_x100={result['reduction_x100']})"
        )


if __name__ == "__main__":
    main()
