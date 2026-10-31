# 黄金测试向量（Golden Vectors）

本目录包含固定的 PGM 图像与 JSON 参考结果，用于确定 FPGA 功能验证的基准。

| 测试向量 | 验证内容 | 预期最大 ROI |
| --- | --- | --- |
| `small_5x5` | 小尺寸图像边界处理 | `x=1, y=1, width=2, height=3` |
| `single_target_640x480` | 单目标区域筛选 | `x=160, y=160, width=160, height=160` |
| `multi_target_640x480` | 多目标最大区域筛选 | `x=80, y=80, width=240, height=160` |
| `noise_target_640x480` | 低幅噪声背景下的单目标筛选 | `x=400, y=160, width=160, height=160` |

每组测试向量包含 `_input.pgm`、`_edge.pgm`、`_roi.json` 和 `_summary.json` 文件。PGM 文件采用 8 位灰度 P5 格式；JSON 汇总文件记录固定阈值、网格划分、选中 ROI 及面积缩减率。

在仓库根目录执行以下命令，可通过参考模型重新生成测试向量：python src/fpga_edge_vision/software/python_ref/cpu_reference.py --write-golden-vectors  


