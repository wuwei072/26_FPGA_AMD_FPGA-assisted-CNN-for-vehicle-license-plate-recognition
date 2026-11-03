# 测试数据与参考结果

本目录提供图像处理模块的输入、Golden、HDL 向量和已有软件参考结果，用于复现与功能比对。

| 目录 | 数量 | 内容 |
|---|---:|---|
| [input](input/) | 4 | 阶跃图、单目标、多目标、噪声场景 |
| [golden_vectors](golden_vectors/readme.md) | 17 | 四组输入 PGM、Sobel 幅值 PGM、ROI JSON、summary JSON 和说明 |
| [hdl_vectors](hdl_vectors/) | 9 | 三组 640×480 的输入 BIN、期望幅值 BIN 和网格计数 HEX |
| [reference_results](reference_results/) | 10 | 软件参考输出图、ROI 标注图和 JSON 汇总；图像别名见下表 |

加本 README 共 41 个文件。

## 文件格式与参考语义

- PGM 为 8 位灰度数据；`input/` 包括 P2、P5，`golden_vectors/` 使用 P5。应解析格式头，不能一律截去固定 15 字节。
- 640×480 raw BIN 无头，uint8、行优先、每像素 1 字节，每份恰好 307200 字节。
- Golden `*_edge.pgm`、HDL `*_expected.bin` 保存饱和 Sobel 幅值，外圈为零。FPGA 返回 0/255 二值图；比较前将幅值按 `>=80` 转为 255，否则为 0。
- 每个 `*_grid_counts.hex` 含 48 项四位十六进制计数，按 8 列×6 行逐行排列。
- `small_5x5` 仅用于软件边界测试；另外三组 640×480 用于当前 RTL 和板端验证。
- 历史参考 JSON 的路径、耗时为原运行记录，不能当作实体板测、纯算法性能或 CNN 准确率证据。

算法阈值、ROI 六字段和接口规则见[接口规格](../docs/fpga_interface_spec.md)。三组硬件向量的完整期望字段见[RTL 仿真说明](../sim/README.md#运行六组测试)。

## 验证入口

离线测试、参考结果输出与 Golden 生成见[软件参考模型说明](../src/fpga_edge_vision/software/python_ref/readme.md)。常规验证直接使用 `hdl_vectors/` 中的 6 个 BIN 和 3 个 HEX，无需重新生成；不要为得到 PASS 修改冻结参考。板端所需 6 个 BIN 在独立部署包中保留副本。

## 参考图像路径映射

下列名称对应相同像素数据，路径相对于 data 目录；需要使用别名时，可从对应位置复制并使用该名称。

| 参考图像名称（别名） | 文件位置 |
|---|---|
| `reference_results/sample_vertical_step_edge.pgm` | [golden_vectors/small_5x5_edge.pgm](golden_vectors/small_5x5_edge.pgm) |
| `reference_results/sample_vertical_step_original.pgm` | [golden_vectors/small_5x5_input.pgm](golden_vectors/small_5x5_input.pgm) |
| `reference_results/synthetic_geometry_original.pgm` | [input/synthetic_geometry.pgm](input/synthetic_geometry.pgm) |
| `reference_results/synthetic_geometry_roi.pgm` | [input/synthetic_geometry.pgm](input/synthetic_geometry.pgm) |
| `reference_results/synthetic_multi_target_original.pgm` | [input/synthetic_multi_target.pgm](input/synthetic_multi_target.pgm) |
| `reference_results/synthetic_multi_target_roi.pgm` | [input/synthetic_multi_target.pgm](input/synthetic_multi_target.pgm) |
| `reference_results/synthetic_noise_original.pgm` | [input/synthetic_noise.pgm](input/synthetic_noise.pgm) |

CNN 模型位于 `src/plate_lpr_server/models/`，不放于本目录。
