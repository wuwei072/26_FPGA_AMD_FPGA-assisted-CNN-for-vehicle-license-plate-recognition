# 黄金测试向量（Golden Vectors）

本目录的固定 PGM 图像与 JSON 结果用于功能比对：

| 测试向量 | 验证内容 | ROI 参考结果 |
|---|---|---|
| `small_5x5` | 软件边界与小尺寸网格处理 | [roi.json](small_5x5_roi.json) |
| `single_target_640x480` | 单个 2×2 活跃网格目标 | [roi.json](single_target_640x480_roi.json) |
| `multi_target_640x480` | 6 格目标与 1 格目标的最大区域筛选 | [roi.json](multi_target_640x480_roi.json) |
| `noise_target_640x480` | 确定性低幅噪声背景下的目标筛选 | [roi.json](noise_target_640x480_roi.json) |

每组含 `_input.pgm`、`_edge.pgm`、`_roi.json` 和 `_summary.json`。summary 记录阈值、网格、选中 ROI 及面积缩减率；文件格式、幅值与硬件二值图的比较方式见[数据说明](../README.md)。

正常验证不重写冻结基准。离线测试及重新生成命令见[参考模型说明](../../src/fpga_edge_vision/software/python_ref/readme.md)。
