"""CPU 参考模型的自动化测试"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_reference import annotate_rois, fpga_mainline_roi, grid_rois, run_pipeline, sobel_edge, validate_image, write_pgm


class CpuReferenceTests(unittest.TestCase):
    def setUp(self):
        self.image = [[0 if x < 4 else 255 for x in range(8)] for _ in range(8)]

    def test_edge_size_and_8_bit_range(self):
        edge = sobel_edge(self.image)
        # 边缘图尺寸必须与输入完全一致
        self.assertEqual(validate_image(edge), (8, 8))
        self.assertTrue(all(isinstance(pixel, int) and 0 <= pixel <= 255 for row in edge for pixel in row))
        self.assertEqual(len(bytes(pixel for row in edge for pixel in row)), 64)

    def test_roi_coordinates_are_in_bounds(self):
        edge = sobel_edge(self.image)
        _, rois = grid_rois(edge)
        for roi in rois:
            self.assertGreaterEqual(roi["x"], 0)
            self.assertGreaterEqual(roi["y"], 0)
            self.assertLessEqual(roi["x"] + roi["width"], 8)
            self.assertLessEqual(roi["y"] + roi["height"], 8)
        self.assertEqual(validate_image(annotate_rois(self.image, rois)), (8, 8))

    def test_small_image_grid_has_no_zero_sized_cells(self):
        # 5×5 小图会自动限制为 5×5 网格
        image = [[0] * 5 for _ in range(5)]
        with self.assertWarns(UserWarning):
            statistics, _ = grid_rois(sobel_edge(image))
        self.assertEqual(len(statistics), 25)
        self.assertTrue(all(cell["width"] > 0 and cell["height"] > 0 for cell in statistics))

    def test_640_by_480_grid_is_8_by_6_with_80_by_80_cells(self):
        image = [[0] * 640 for _ in range(480)]
        statistics, _ = grid_rois(sobel_edge(image))
        self.assertEqual(len(statistics), 48)
        self.assertTrue(all(cell["width"] == 80 and cell["height"] == 80 for cell in statistics))

    def test_largest_grid_component_is_selected(self):
        edge = [[0] * 640 for _ in range(480)]
        for grid_y, grid_x in ((1, 1), (1, 2), (2, 1), (2, 2), (4, 6)):
            for y in range(grid_y * 80, (grid_y + 1) * 80):
                for x in range(grid_x * 80, (grid_x + 1) * 80):
                    edge[y][x] = 255
        statistics, components, largest = fpga_mainline_roi(edge)
        self.assertEqual(len(statistics), 48)
        self.assertEqual(len(components), 2)
        self.assertEqual(largest, {"x": 80, "y": 80, "width": 160, "height": 160, "grid_cell_count": 4})

    def test_pipeline_writes_three_images_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir, result_dir = root / "data" / "input", root / "results"
            input_dir.mkdir(parents=True)
            write_pgm(input_dir / "step.pgm", self.image)
            summaries = run_pipeline(root / "data", result_dir)
            self.assertEqual(len(summaries), 1)
            for suffix in ("original.pgm", "edge.pgm", "roi.pgm", "summary.json"):
                self.assertTrue((result_dir / f"step_{suffix}").is_file())
            self.assertTrue((result_dir / "run_summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
