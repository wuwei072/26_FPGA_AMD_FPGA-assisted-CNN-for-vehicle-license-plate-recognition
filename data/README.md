# 测试数据与参考结果

本目录集中提供图像处理模块的输入、黄金参考、HDL向量和已有软件参考结果。它们用于复现与功能比对；其中合成图片及软件输出不作为真实车牌识别准确率、实体板测试或硬件性能的实测证据。

## 目录

| 目录 | 数量 | 内容 |
|---|---:|---|
| input/ | 4 | 参考模型输入示例：阶跃图、单目标、多目标、噪声场景 |
| golden_vectors/ | 17 | 四组输入PGM、Sobel幅值PGM、ROI JSON、summary JSON和说明 |
| hdl_vectors/ | 9 | 三组640×480场景的输入BIN、参考幅值BIN与48网格计数HEX |
| reference_results/ | 17 | 已有Python参考运行的输出图、ROI标注图和JSON汇总 |

加上本README，共48个文件。small_5x5用于软件边界测试；固定640×480的RTL/板端测试使用其余三组向量。

## 参考语义

- PGM为8位灰度数据；大图640×480。
- Golden的`*_edge.pgm`与HDL的`*_expected.bin`保存饱和后的Sobel幅值；FPGA回传二值图。比较前按阈值80转换：幅值>=80为255，否则0，外圈为0。
- BIN按行优先，每像素1字节，无PGM头部；每份大图BIN恰好307200字节。
- `*_grid_counts.hex`包含48项网格计数，供ROI模块参考使用。
- ROI JSON和summary说明是软件黄金答案；RTL验证日志在仓库sim/logs，实体板测结果应另存board/measurements。

三组硬件向量期望六字段为：

| 场景 | x,y,width,height,best_grids,reduction_x100 |
|---|---|
| single_target | 160,160,160,160,4,9167 |
| multi_target | 80,80,240,160,6,8750 |
| noise_target | 400,160,160,160,4,9167 |

## 与源码目录的对应关系

本目录是便于评审查阅的分类副本；现有脚本仍从源码子工程内部位置读取。保留内部数据，避免破坏原有相对路径。

| 本目录 | 源码内原位置 |
|---|---|
| input/ | src/fpga_edge_vision/data/input/ |
| golden_vectors/ | src/fpga_edge_vision/data/golden_vectors/ |
| hdl_vectors/ | src/fpga_edge_vision/hardware/sim/vectors/ |
| reference_results/ | src/fpga_edge_vision/results/python_ref/ |

重新生成或验证时，以`src/fpga_edge_vision`作为工作目录，再按其说明运行。golden_vectors/readme.md里的原有命令也以该源码子工程根目录为执行位置。不要为消除差异随意改写黄金参考；算法变化后应重新确认契约，并同步两处副本。

CNN预训练模型位于仓库`src/plate_lpr_server/models/`，没有混放在本测试数据目录。
