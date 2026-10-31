# 黄金测试向量（Golden Vectors）

本目录包含固定的 PGM 图像与 JSON 参考结果，用于确定 FPGA 功能验证的基准。

| 测试向量 | 验证内容 | 预期最大 ROI |
| --- | --- | --- |
| `small_5x5` | 边界处理与小尺寸图像的网格适配 | `x=1, y=1, width=2, height=3` |
| `single_target_640x480` | 单个占据 2×2 活跃网格的目标 | `x=160, y=160, width=160, height=160` |
| `multi_target_640x480` | 从分别占据 6 格与 1 格的目标中选择最大区域 | `x=80, y=80, width=240, height=160` |
| `noise_target_640x480` | 固定低幅度噪声背景下的单目标筛选 | `x=400, y=160, width=160, height=160` |

每组测试向量包含 `_input.pgm`、`_edge.pgm`、`_roi.json` 和 `_summary.json` 文件。PGM 文件采用 8 位灰度 P5 格式；JSON 汇总文件记录固定阈值、网格划分、选中 ROI 及面积缩减率。

在仓库根目录执行以下命令，可通过参考模型重新生成测试向量：

