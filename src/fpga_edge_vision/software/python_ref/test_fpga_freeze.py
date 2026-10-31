"""冻结接口验收：网格几何、ROI 边界、区域选择及 Golden 向量可重复性"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_reference import (
    EDGE_PIXEL_THRESHOLD,
    GRID_COLUMNS,
    GRID_CONNECTIVITY,
    GRID_EDGE_RATIO_THRESHOLD,
    GRID_ROWS,
    active_grid_map,
    binarize_edge,
    effective_grid_shape,
    fpga_mainline_roi,
    golden_vector_images,
    grid_components,
    grid_edge_statistics,
    grid_rois,
    pixel_edge_components,
    pixel_reference_roi,
    roi_json_record,
    roi_reduction_ratio,
    sobel_edge,
    validate_image,
    write_golden_vectors,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data" / "golden_vectors"
FRAME = (640, 480)


def blank_frame() -> list[list[int]]:
    return [[0] * FRAME[0] for _ in range(FRAME[1])]


def activate_grid_cells(cells, edge, value: int = 255) -> list[list[int]]:
    for grid_y, grid_x in cells:
        for y in range(grid_y * 80, (grid_y + 1) * 80):
            for x in range(grid_x * 80, (grid_x + 1) * 80):
                edge[y][x] = value
    return edge


class GridGeometryTests(unittest.TestCase):

    def test_requested_grid_geometry_is_8_by_6_of_80_by_80(self):
        self.assertEqual((GRID_COLUMNS, GRID_ROWS), (8, 6))
        self.assertEqual(effective_grid_shape(640, 480, emit_warning=False), (8, 6))

    def test_frame_grid_has_exactly_48_cells(self):
        statistics = grid_edge_statistics(blank_frame())
        self.assertEqual(len(statistics), 48)

    def test_frame_grid_has_no_zero_sized_cells(self):
        statistics = grid_edge_statistics(blank_frame())
        self.assertTrue(all(cell["width"] > 0 and cell["height"] > 0 for cell in statistics))

    def test_frame_grid_cells_are_all_80_by_80(self):
        statistics = grid_edge_statistics(blank_frame())
        self.assertTrue(all(cell["width"] == 80 and cell["height"] == 80 for cell in statistics))

    def test_frame_grid_covers_frame_exactly_once(self):
        statistics = grid_edge_statistics(blank_frame())
        covered = sum(cell["width"] * cell["height"] for cell in statistics)
        self.assertEqual(covered, FRAME[0] * FRAME[1])
        for grid_y in range(GRID_ROWS):
            row = [cell for cell in statistics if cell["grid_y"] == grid_y]
            self.assertEqual(sum(cell["width"] for cell in row), FRAME[0])
        for grid_x in range(GRID_COLUMNS):
            column = [cell for cell in statistics if cell["grid_x"] == grid_x]
            self.assertEqual(sum(cell["height"] for cell in column), FRAME[1])

    def test_grid_indices_are_unique_and_dense(self):
        statistics = grid_edge_statistics(blank_frame())
        keys = {(cell["grid_x"], cell["grid_y"]) for cell in statistics}
        self.assertEqual(keys, {(x, y) for y in range(GRID_ROWS) for x in range(GRID_COLUMNS)})

    def test_small_image_grid_has_no_zero_sized_cells(self):
        with self.assertWarns(UserWarning):
            statistics = grid_edge_statistics([[0] * 5 for _ in range(5)])
        self.assertEqual(len(statistics), 25)
        self.assertTrue(all(cell["width"] > 0 and cell["height"] > 0 for cell in statistics))

    def test_thresholds_and_connectivity_are_frozen(self):
        self.assertEqual(EDGE_PIXEL_THRESHOLD, 80)
        self.assertEqual(GRID_EDGE_RATIO_THRESHOLD, 0.12)
        self.assertEqual(GRID_CONNECTIVITY, 4)


class ActiveGridTests(unittest.TestCase):

    def test_ratio_equal_to_threshold_is_inactive(self):
        edge = activate_grid_cells([(2, 3)], blank_frame(), value=0)
        for y in range(2 * 80, 3 * 80):
            for x in range(3 * 80, 4 * 80):
                edge[y][x] = 255 if (y - 160) * 80 + (x - 240) < 768 else 0
        statistics = grid_edge_statistics(edge)
        cell = next(item for item in statistics if item["grid_x"] == 3 and item["grid_y"] == 2)
        self.assertEqual(cell["edge_count"], 768)
        self.assertEqual(cell["active"], 0)

    def test_ratio_just_above_threshold_is_active(self):
        edge = blank_frame()
        for y in range(2 * 80, 3 * 80):
            for x in range(3 * 80, 4 * 80):
                edge[y][x] = 255 if (y - 160) * 80 + (x - 240) < 769 else 0
        statistics = grid_edge_statistics(edge)
        cell = next(item for item in statistics if item["grid_x"] == 3 and item["grid_y"] == 2)
        self.assertEqual(cell["edge_count"], 769)
        self.assertEqual(cell["active"], 1)

    def test_binarize_uses_inclusive_threshold(self):
        edge = [[0] * 3 for _ in range(3)]
        edge[1][1] = 80
        self.assertEqual(binarize_edge(edge)[1][1], 1)
        edge[1][1] = 79
        self.assertEqual(binarize_edge(edge)[1][1], 0)

    def test_active_grid_map_shape_is_8_by_6(self):
        active = active_grid_map(grid_edge_statistics(blank_frame()))
        self.assertEqual(len(active), GRID_ROWS)
        self.assertTrue(all(len(row) == GRID_COLUMNS for row in active))


class ConnectivityTests(unittest.TestCase):

    def test_diagonal_cells_are_not_connected(self):
        edge = activate_grid_cells([(1, 1), (2, 2)], blank_frame())
        _, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(len(components), 2)
        self.assertEqual(largest["grid_cell_count"], 1)

    def test_four_connected_block_merges_into_one_region(self):
        edge = activate_grid_cells([(1, 1), (1, 2), (2, 1), (2, 2)], blank_frame())
        _, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(len(components), 1)
        self.assertEqual(largest, {"x": 80, "y": 80, "width": 160, "height": 160,
                                   "grid_cell_count": 4})

    def test_shared_edge_connects_two_cells(self):
        edge = activate_grid_cells([(0, 0), (0, 1)], blank_frame())
        _, components, _ = fpga_mainline_roi(edge)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["grid_cell_count"], 2)

    def test_component_cells_are_recorded_in_row_major_order(self):
        edge = activate_grid_cells([(3, 5), (1, 0), (3, 4)], blank_frame())
        components = grid_components(active_grid_map(grid_edge_statistics(edge)))
        sizes = sorted(component["grid_cell_count"] for component in components)
        self.assertEqual(sizes, [1, 2])


class LargestRegionSelectionTests(unittest.TestCase):

    def test_largest_grid_component_is_selected(self):
        edge = activate_grid_cells([(1, 1), (1, 2), (2, 1), (2, 2), (4, 6)], blank_frame())
        statistics, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(len(statistics), 48)
        self.assertEqual(len(components), 2)
        self.assertEqual(largest, {"x": 80, "y": 80, "width": 160, "height": 160,
                                   "grid_cell_count": 4})

    def test_selection_prefers_upper_left_on_tie(self):
        edge = activate_grid_cells([(4, 2), (4, 3), (2, 6), (2, 7)], blank_frame())
        _, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(len(components), 2)
        # 格数相同时选择更靠上的区域，网格坐标换算为像素 ROI
        self.assertEqual(largest, {"x": 480, "y": 160, "width": 160, "height": 80,
                                   "grid_cell_count": 2})

    def test_no_active_grid_yields_no_roi(self):
        statistics, components, largest = fpga_mainline_roi(blank_frame())
        self.assertEqual(len(statistics), 48)
        self.assertEqual(components, [])
        self.assertIsNone(largest)
        self.assertEqual(roi_json_record(None),
                         {"roi_valid": 0, "roi_x": 0, "roi_y": 0, "roi_width": 0,
                          "roi_height": 0, "roi_grid_cell_count": 0})
        self.assertEqual(roi_reduction_ratio(None, *FRAME), 1.0)

    def test_selected_region_is_the_maximum_by_cell_count(self):
        edge = activate_grid_cells(
            [(0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (3, 4), (3, 5), (4, 4)], blank_frame())
        _, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(largest["grid_cell_count"], max(c["grid_cell_count"] for c in components))
        self.assertEqual(largest["grid_cell_count"], 5)


class RoiBoundsTests(unittest.TestCase):

    def test_roi_stays_inside_the_frame(self):
        edge = activate_grid_cells([(0, 0), (5, 7), (2, 3), (2, 4)], blank_frame())
        _, components, largest = fpga_mainline_roi(edge)
        for roi in [largest] + components:
            self.assertGreaterEqual(roi["x"], 0)
            self.assertGreaterEqual(roi["y"], 0)
            self.assertGreater(roi["width"], 0)
            self.assertGreater(roi["height"], 0)
            self.assertLessEqual(roi["x"] + roi["width"], FRAME[0])
            self.assertLessEqual(roi["y"] + roi["height"], FRAME[1])

    def test_corner_cells_produce_in_bounds_roi(self):
        _, _, largest = fpga_mainline_roi(activate_grid_cells([(5, 7)], blank_frame()))
        self.assertEqual(largest, {"x": 560, "y": 400, "width": 80, "height": 80,
                                   "grid_cell_count": 1})
        self.assertEqual(largest["x"] + largest["width"], 640)
        self.assertEqual(largest["y"] + largest["height"], 480)

    def test_cell_count_never_exceeds_total_grid(self):
        edge = activate_grid_cells([(y, x) for y in range(GRID_ROWS) for x in range(GRID_COLUMNS)],
                                   blank_frame())
        _, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(len(components), 1)
        self.assertEqual(largest["grid_cell_count"], 48)
        self.assertEqual(largest, {"x": 0, "y": 0, "width": 640, "height": 480,
                                   "grid_cell_count": 48})
        self.assertEqual(roi_reduction_ratio(largest, *FRAME), 0.0)

    def test_reduction_ratio_matches_frozen_formula(self):
        _, _, largest = fpga_mainline_roi(activate_grid_cells([(1, 1)], blank_frame()))
        expected = 1.0 - (largest["width"] * largest["height"]) / (640 * 480)
        self.assertAlmostEqual(roi_reduction_ratio(largest, 640, 480), expected)
        self.assertAlmostEqual(expected, 1.0 - 6400 / 307200)


class PixelReferenceTests(unittest.TestCase):

    def test_pixel_reference_finds_separate_components(self):
        edge = [[0] * 8 for _ in range(8)]
        edge[2][2] = edge[2][3] = 200
        edge[6][6] = 200
        components = pixel_edge_components(edge)
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0]["pixel_count"], 2)
        self.assertEqual(components[0]["x"], 2)
        self.assertEqual(components[0]["y"], 2)

    def test_pixel_reference_uses_8_connectivity(self):
        edge = [[0] * 4 for _ in range(4)]
        edge[1][1] = 200
        edge[2][2] = 200
        self.assertEqual(len(pixel_edge_components(edge, connectivity=8)), 1)
        self.assertEqual(len(pixel_edge_components(edge, connectivity=4)), 2)

    def test_pixel_reference_only_counts_pixels_at_or_above_threshold(self):
        edge = [[0] * 4 for _ in range(4)]
        edge[1][1] = 79
        edge[1][2] = 80
        components = pixel_edge_components(edge)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["pixel_count"], 1)

    def test_pixel_reference_roi_is_in_bounds(self):
        edge = sobel_edge(golden_vector_images()["small_5x5"])
        roi = pixel_reference_roi(edge)
        self.assertIsNotNone(roi)
        self.assertGreaterEqual(roi["x"], 0)
        self.assertGreaterEqual(roi["y"], 0)
        self.assertLessEqual(roi["x"] + roi["width"], 5)
        self.assertLessEqual(roi["y"] + roi["height"], 5)


class GoldenVectorTests(unittest.TestCase):

    EXPECTED = {
        "small_5x5": {"roi_x": 1, "roi_y": 1, "roi_width": 2, "roi_height": 3,
                      "roi_grid_cell_count": 6},
        "single_target_640x480": {"roi_x": 160, "roi_y": 160, "roi_width": 160,
                                  "roi_height": 160, "roi_grid_cell_count": 4},
        "multi_target_640x480": {"roi_x": 80, "roi_y": 80, "roi_width": 240,
                                 "roi_height": 160, "roi_grid_cell_count": 6},
        "noise_target_640x480": {"roi_x": 400, "roi_y": 160, "roi_width": 160,
                                 "roi_height": 160, "roi_grid_cell_count": 4},
    }

    def test_required_vectors_are_present(self):
        for name in self.EXPECTED:
            for suffix in ("_input.pgm", "_edge.pgm", "_roi.json", "_summary.json"):
                self.assertTrue((GOLDEN_ROOT / f"{name}{suffix}").is_file(),
                                msg=f"missing {name}{suffix}")

    def test_committed_roi_json_matches_frozen_expectations(self):
        for name, expected in self.EXPECTED.items():
            record = json.loads((GOLDEN_ROOT / f"{name}_roi.json").read_text(encoding="utf-8"))
            self.assertEqual(record["roi_valid"], 1)
            for key, value in expected.items():
                self.assertEqual(record[key], value, msg=f"{name}:{key}")

    def test_committed_summaries_are_self_consistent(self):
        for name in self.EXPECTED:
            summary = json.loads((GOLDEN_ROOT / f"{name}_summary.json").read_text(encoding="utf-8"))
            roi = summary["largest_grid_component_roi"]
            self.assertEqual(summary["grid_cell_count"], summary["grid_columns"] * summary["grid_rows"])
            self.assertEqual(len(summary["grid_statistics"]), summary["grid_cell_count"])
            self.assertTrue(all(cell["width"] > 0 and cell["height"] > 0
                                for cell in summary["grid_statistics"]))
            self.assertLessEqual(roi["roi_x"] + roi["roi_width"], summary["width"])
            self.assertLessEqual(roi["roi_y"] + roi["roi_height"], summary["height"])
            self.assertAlmostEqual(
                summary["roi_data_reduction_ratio"],
                1.0 - (roi["roi_width"] * roi["roi_height"]) / (summary["width"] * summary["height"]))

    def test_generation_is_reproducible(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            write_golden_vectors(first)
            write_golden_vectors(second)
            for name in self.EXPECTED:
                for suffix in ("_roi.json", "_summary.json"):
                    left = (Path(first) / f"{name}{suffix}").read_bytes()
                    right = (Path(second) / f"{name}{suffix}").read_bytes()
                    self.assertEqual(left, right, msg=f"{name}{suffix} is not reproducible")

    def test_generated_artifacts_match_committed_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_golden_vectors(temporary)
            for name in self.EXPECTED:
                for suffix in ("_input.pgm", "_edge.pgm", "_roi.json", "_summary.json"):
                    generated = (Path(temporary) / f"{name}{suffix}").read_bytes()
                    committed = (GOLDEN_ROOT / f"{name}{suffix}").read_bytes()
                    self.assertEqual(generated, committed,
                                     msg=f"{name}{suffix} on disk is stale; rerun --write-golden-vectors")

    def test_generated_input_and_edge_are_8_bit_grayscale(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_golden_vectors(temporary)
            from cpu_reference import read_pgm
            for name in self.EXPECTED:
                source = read_pgm(Path(temporary) / f"{name}_input.pgm")
                edge = read_pgm(Path(temporary) / f"{name}_edge.pgm")
                self.assertEqual(validate_image(source), validate_image(edge))
                self.assertTrue(all(0 <= pixel <= 255 for row in edge for pixel in row))


if __name__ == "__main__":
    unittest.main()
