# FPGA 协同 CNN 辅助车牌识别


本项目基于 PYNQ-Z2 实现 FPGA 与 CNN 协同的车牌识别系统。FPGA 完成边缘提取与候选区域筛选，板端负责视频采集和抓拍调度，电脑端完成画面展示与车牌识别，支持手动抓拍、自动识别确认后保存及同帧软硬件对比。
![系统架构](src/fpga_edge_vision/docs/figures/method_draw_http_roi_edited.png)

- **目标平台：** PYNQ-Z2，Xilinx Zynq-7000 XC7Z020
- **开发工具：** AMD Vivado 2025.1、Python

## 项目概览

| 部分 | 主要职责 | 目录 |
|---|---|---|
| PL 硬件 | Sobel 边缘提取、网格统计、四连通 ROI 筛选、双 AXI DMA | [hardware/](hardware/) |
| PS 软件 | 视频采集、DMA 调用、稳定判定、抓拍与异步识别调度 | [deploy/](deploy/) |
| PyQt5 客户端 | 双画面显示、ROI 预览、远程控制与指标展示 | [software/pc/](software/pc/) |
| PC 识别服务 | 预训练模型推理、车牌识别与自动保存许可 | 独立部署 |

部署版支持手动抓拍与稳定目标自动抓拍。自动模式需目标持续稳定，并以识别服务返回的许可决定是否保存；实际使用受背景、距离、角度和光照影响。候选区域来自边缘密度，不能单凭 ROI 判定车牌类别。

### 数据通路与接口

```text
USB 摄像头 -> ARM 灰度帧 -> 主 DMA MM2S -> Sobel -> 分流
                                                   |-> 网格 / ROI -> 主 DMA S2MM -> 12 B 元数据
                                                   `-> 边缘 DMA S2MM -> 307200 B 二值边缘图
ARM 用 ROI 坐标裁剪同帧彩色图 -> HTTP 识别服务
ARM -> TCP 原图 / 边缘图 / 状态 -> 电脑 PyQt5
```

| 项目 | 当前规格 |
|---|---|
| 板卡 / 器件 | PYNQ-Z2，`xc7z020clg400-1` |
| PL 时钟 | 50 MHz |
| 输入 | 640×480、uint8 灰度、行优先，共 307200 B |
| Sobel | `min(255, abs(Gx) + abs(Gy))`，最外圈清零，阈值 `>=80` 输出 255 |
| 网格 | 8 列 × 6 行，每格 80×80，`edge_count > 768` 为活跃格 |
| ROI 选择 | 四连通，保留活跃格数最多的区域；并列保留先按行扫描到的区域 |
| ROI 回传 | 六个 uint16：`x, y, width, height, best_grids, reduction_x100` |
| 视频 / 控制 | 板端 TCP 8080 / 8081 |
| 识别接口 | 电脑 HTTP 5000，`POST /api/recognize`；健康检查 `GET /health` |

算法边界和黄金参考语义见 [接口规格](src/fpga_edge_vision/docs/fpga_interface_spec.md)。候选区域面积缩减率描述 ROI 大小；当前仍回传完整边缘图，不能将面积缩减直接写成实际 DMA 带宽或 CNN 推理耗时的等比例下降。

## 2. 目录说明

本工程按提交材料组织外层目录，并保留源码子工程的内部路径，便于原有构建及验证脚本读取依赖。

```text
fpga_lpr/
├── README.md
├── src/
│   ├── fpga_edge_vision/
│   │   ├── hardware/rtl/                         当前 RTL 与历史文件
│   │   ├── hardware/sim/                         Testbench、向量与历史日志
│   │   ├── hardware/vivado/sobel_edge_system/    真实构建脚本、约束及 output
│   │   ├── software/pc/                         PyQt5 客户端
│   │   ├── software/pynq/                       板端源码，见第 9 节版本说明
│   │   ├── software/python_ref/                 参考模型、OpenCV 对照与测试
│   │   ├── data/                               实际测试输入与 Golden
│   │   ├── results/python_ref/                  已有参考输出
│   │   ├── docs/                               接口、部署说明与图源
│   │   ├── scripts/                            打包工具，见第 9 节
│   │   └── upload_to_jupyter_notebook/          另一份部署副本
│   └── plate_lpr_server/                        电脑识别服务、依赖和模型
├── board/
│   ├── deploy/                                 本文指定的板端运行包
│   ├── board_files/pynq_z2/A.0/                 PYNQ-Z2 板卡配置
│   └── measurements/                           实测日志、照片和计时数据，待补
├── build/
│   ├── rebuild.tcl                             外层硬件构建入口
│   └── reports/                                时序、资源、详细报告和 BD 快照
├── data/README.md                              指向源码内数据，不重复存放
├── sim/                                        外层仿真证据归档，待补
├── skill/                                      四项可复用技能及自检
└── report/                                     设计报告及协作记录，待补
```

| 推荐提交分类 | 本工程实际位置 |
|---|---|
| 设计源码 | `src/fpga_edge_vision/hardware/rtl/`、`software/` 和 `src/plate_lpr_server/` |
| 仿真脚本 / 数据 | `src/fpga_edge_vision/hardware/sim/` 与 `software/python_ref/` |
| 构建入口 / 报告 | `build/rebuild.tcl`、`build/reports/` |
| 上板运行包 | `board/deploy/` |
| 测试输入 / 黄金答案 | `src/fpga_edge_vision/data/input/`、`data/golden_vectors/` |
| 已有 CPU 参考结果 | `src/fpga_edge_vision/results/python_ref/` |
| 技能包 | `skill/` |
| 设计报告 / 大模型记录 | `report/`，当前尚未放入成稿与原始记录 |

`venv/`、`__pycache__/` 和服务运行生成的 `.tmp/`、`server.pid` 不作为源码提交。环境在实际运行位置重新建立。生成工程、缓存和重复副本可在确认报告与证据已归档后精简。

## 3. 环境准备

### 硬件

- PYNQ-Z2 开发板、带 PYNQ 镜像的 Micro SD 卡、适配电源。
- USB 摄像头接开发板 USB Host；网线连接开发板与电脑。
- 电脑运行 PyQt5 和识别服务，双方 IP 可达。

### 软件

| 执行位置 | 依赖 |
|---|---|
| PYNQ 板端 | PYNQ Python 环境、`pynq`、NumPy、OpenCV；摄像头可由 OpenCV 打开 |
| Windows 电脑界面 | Python 3.12，`PyQt5==5.15.11`，见 [界面依赖](src/fpga_edge_vision/software/pc/requirements.txt) |
| Windows 电脑识别 | Python 3.12；见 [识别依赖](src/plate_lpr_server/requirements.txt)，已有模型 ZIP 和三个 ONNX |
| 硬件重建电脑 | Vivado 2025.1、PYNQ-Z2 board files；其他工具版本需自行复核 |
| 离线参考测试 | Python 标准库；OpenCV 同帧对照另外依赖 NumPy / OpenCV |

现有服务环境的 Python 版本记录为 3.12.14。当前识别依赖表固定了主要依赖；在全新电脑上的安装与模型推理仍需验收。PYNQ 镜像、板端 Python / NumPy / OpenCV 的实际版本应随最终板测记录补充。

下文 Windows 示例假定本仓库在 `D:\fpga_lpr`。放到其他位置时，只替换仓库根路径。`py -3.12` 需 Windows 已安装 Python 3.12；也可用该解释器的完整路径替代。

## 4. 使用已有 Overlay 部署运行

### 4.1 准备网络与板端文件

本文示例：电脑 IP `192.168.2.1`，板子 IP `192.168.2.99`；按实际网络替换。`--pc-ip` 填识别服务所在电脑地址，GUI 的 `--host` 填板子地址。

将 [board/deploy](board/deploy/) **里面的全部内容**上传到板端同一目录，例如：

```text
/home/xilinx/jupyter_notebooks/fpga_lpr/
  pynq_video_server.py
  video_protocol.py
  edge_dma_runtime.py
  opencv_benchmark.py
  sobel_edge.bit
  sobel_edge.hwh
  validation/
  board_check/
  README.md
  UPLOAD_MANIFEST.json
```

保留所有子目录；`.bit/.hwh` 同名配对，验证目录保留全部六个 BIN。上传目录叫什么不影响服务，只需与后续 `cd` 和脚本文件位置一致。停止旧摄像头 / DMA 任务后再开始验证。

### 4.2 先做板端 Golden 验证

以下命令在 **PYNQ Linux 终端**执行，使用板上可导入 PYNQ 的 Python：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_lpr
sudo -E python3 validation/edge_return_test.py
```

验收标志：三组单目标、多目标、噪声向量均 `PASS`，`edge mismatches` 和 `border nonzero` 均为 `0`，最终显示 `ALL PASS`。参考 BIN 是 Sobel 幅值，脚本按阈值 80 转换后比较硬件二值图。未通过时先保存原始输出并排查；DMA 超时后按提示重启板子，再独立复测。

### 4.3 电脑上安装并启动 CNN 识别服务

首次在 **Windows PowerShell**执行：

```powershell
Set-Location 'D:\fpga_lpr\src\plate_lpr_server'
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\venv\Scripts\python.exe .\prepare_models.py
.\start_server.cmd
```

必须新建本目录的 `venv`。`prepare_models.py` 除了准备权重，还会配置 HyperLPR3 使用本地模型；即使三个 ONNX 已存在，新建环境后也要执行一次。随后启动通常只需运行 `start_server.cmd`；停止用 Ctrl+C 或 `stop_server.cmd`。详细说明见 [识别服务](src/plate_lpr_server/README.md)。

另一 PowerShell 窗口检查：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/health'
```

应返回 `status: ok` 和 `auto_save_policy: plate-confirmed-v2`。健康检查表明服务和模型已初始化；识别质量仍需用真实图片验证。Windows 网络设置应允许板子访问电脑 TCP 5000。

### 4.4 启动板端视频服务

完成 Golden 测试并结束测试进程后，在 **PYNQ Linux 终端**执行：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_lpr
sudo -E python3 pynq_video_server.py --pc-ip 192.168.2.1 --camera 0 --save-dir /home/xilinx/captures
```

`--camera` 是板上摄像头编号，`--save-dir` 是实际抓拍输出位置。等待服务初始化并监听 TCP 8080 / 8081。按 Ctrl+C 停止，不同时运行其他占用同一摄像头 / Overlay / DMA 的任务。

### 4.5 启动电脑 PyQt5 界面

在 **Windows PowerShell**执行：

```powershell
Set-Location 'D:\fpga_lpr\src\fpga_edge_vision\software\pc'
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\venv\Scripts\python.exe .\pc_dashboard.py --host 192.168.2.99
```

之后无需重复创建环境，直接执行最后一条命令。窗口中确认板子 IP 后点击连接。电脑应可访问板端 TCP 8080 / 8081。

功能验收：双画面正常更新、ROI 对应同帧原图；手动抓拍保存彩色 ROI 并返回识别状态；自动抓拍按部署版规则运行；ARM 对照比较同一帧六字段，并分别记录 FPGA 完整调用与 ARM 耗时。识别失败与无目标场景也应记录。

## 5. 从源码重建硬件

当前构建读取六个 RTL：`sobel_axis.sv`、`grid_counter.sv`、`roi_engine.sv`、`axis_broadcast_1to2.sv`、`sobel_grid_edge_top.sv`、`sobel_grid_edge_top_bd.v`，以及同构建目录的 `sobel_edge_system.xdc`。

在 **Vivado 2025.1 Tcl Console / Tcl Shell**执行：

```tcl
set submission_root [file normalize {D:/fpga_lpr}]
set_param board.repoPaths [list [file join $submission_root board board_files]]
puts [get_board_parts -quiet -filter {BOARD_NAME =~ "*pynq-z2*"} -latest_file_version]
source [file join $submission_root build rebuild.tcl]
```

板卡查询应输出 PYNQ-Z2 board part；若为空，先检查 board repository 配置、重启 Vivado 后重试。`build/rebuild.tcl` 会调用：

```text
src/fpga_edge_vision/hardware/vivado/sobel_edge_system/build_bd.tcl
```

**外层直接复制的 `build/build_bd.tcl` 仍有相对路径问题，不将它作为执行入口。** 构建会在源码子工程内重新生成 `project/` 和 `output/`；预期输出有：

```text
src/fpga_edge_vision/hardware/vivado/sobel_edge_system/output/sobel_edge.bit
src/fpga_edge_vision/hardware/vivado/sobel_edge_system/output/sobel_edge.hwh
src/fpga_edge_vision/hardware/vivado/sobel_edge_system/output/address_map_vivado.txt
```

重新构建后需导出本次实现的时序 / 资源报告，并将配对 `.bit/.hwh` 同步到 `board/deploy/`、刷新文件清单、重新上板验证。已有报告不自动代表新构建的结果。不要直接用现有打包脚本覆盖部署包，当前源码与部署版差异见第 9 节。

## 6. 软件参考、仿真与数据

### 6.1 参考模型自动测试

从 **源码子工程根目录**执行：

```powershell
Set-Location 'D:\fpga_lpr\src\fpga_edge_vision'
py -3.12 -B -m unittest discover -s software/python_ref -p 'test_*.py' -v
```

2026-10-30 对本提交副本执行的 40 项参考模型 / 冻结规则测试全部通过。临时数据在独立审计目录生成，未重写仓库 Golden。这只覆盖离线参考与规则，不代替当前硬件重建和实体板验证。

| 文件 | 用途 |
|---|---|
| `software/python_ref/cpu_reference.py` | 完整纯 Python 算法参考、PGM 处理和 Golden 生成 |
| `software/python_ref/roi_engine_reference.py` | 对网格计数进行 ROI 模块参考计算 |
| `software/python_ref/opencv_benchmark.py` | 板端按需同帧 ARM OpenCV 对照 |
| `test_cpu_reference.py`、`test_fpga_freeze.py` | 基础功能及冻结契约 / Golden 一致性测试 |

输入示例在 [data/input](src/fpga_edge_vision/data/input/)，四组黄金参考在 [data/golden_vectors](src/fpga_edge_vision/data/golden_vectors/)。`small_5x5` 被软件测试使用；三组 640×480 用于固定硬件验证。已有 CPU 结果见 [results/python_ref](src/fpga_edge_vision/results/python_ref/)。外层 `data/` 只作目录对照，不再重复保存数据。

单独生成参考输出可执行：

```powershell
py -3.12 software/python_ref/cpu_reference.py --results results/python_ref_local
```

它会写参考结果，并在缺少示例输入时补生成输入。不要在未审查算法变化时覆盖已冻结 Golden。参考模型输出的 Sobel 幅值与硬件二值图需按明确契约转换后比较。

### 6.2 RTL 仿真

当前双输出仿真顶层：

```text
src/fpga_edge_vision/hardware/sim/tb_sobel_grid_edge_top.sv
```

编译依赖为 `sobel_axis.sv`、`grid_counter.sv`、`roi_engine.sv`、`axis_broadcast_1to2.sv`、`sobel_grid_edge_top.sv`。向量在同级 `vectors/`；单目标参数示例（以实际路径替换根目录）：

```text
+IN=D:/fpga_lpr/src/fpga_edge_vision/hardware/sim/vectors/single_target_640x480_input.bin
+EDGE=D:/fpga_lpr/src/fpga_edge_vision/hardware/sim/vectors/single_target_640x480_expected.bin
+EXPECTED=160,160,160,160,4,9167
```

测试覆盖两帧、独立输出反压、边缘像素 / ROI 和包结束标志。多目标期望为 `80,80,240,160,6,8750`；噪声期望为 `400,160,160,160,4,9167`，同时换对应输入 / 参考文件。

目录中的 `tb_sobel_grid_top.sv`、`sobel_grid_top_bd.v` 是旧 ROI-only 版本的材料；`tb_sobel_3x3_golden.sv` 还依赖当前包中不存在的旧模块。**不将所有历史 Testbench 通配编译成当前验收。** 内层 `hardware/sim/logs/` 的三份旧日志不作为当前双输出完整三组通过的证明。外层 `sim/` 仍待收集当前原始日志。

## 7. 已有实现报告与性能口径

以下来自现有 Vivado 2025.1、50 MHz 双 DMA 实现报告，不是本次重新运行的构建结果：

| 指标 | 数值 |
|---|---:|
| LUT | 5044 / 53200，9.48% |
| FF | 6768 / 106400，6.36% |
| Block RAM Tile | 5.5 / 140，3.93% |
| DSP | 0 / 220 |
| Setup WNS / Hold WHS | +10.360 ns / +0.020 ns |

原始资料：[资源报告](build/reports/current/utilization.rpt)、[时序报告](build/reports/current/timing_summary.rpt)、[地址表](build/reports/current/address_map_vivado.txt)、[详细报告目录](build/reports/generated_runs/)、[BD 快照](build/reports/design_snapshot/sobel_edge_system.bd)。现有功耗报告中的约 1.410 W 是 Vivado 估计，不作为电表实测功耗。

现场 FPS、FPGA 完整调用耗时、同帧 ARM 耗时、CNN 延迟、识别样本统计和功耗实测，需随实际记录补齐；本 README 不填示例性能数值。`FPGA+DMA window`、`Full call`、GUI FPS、模型 `time_ms` 的计时范围不同，应分别标注。

## 8. 可复用技能包

[skill/README.md](skill/README.md) 是技能入口，包含：

- 主机与目标机分层联调 `host-target-bringup`。
- DMA 事务与故障定位 `dma-transaction-debug`。
- 实时系统瓶颈分析 `realtime-bottleneck-profile`。
- Golden 语义与性能证据核验 `golden-evidence-audit`。

无硬件自检：

```powershell
Set-Location 'D:\fpga_lpr\skill'
py -3.12 -B verify_package.py
```

适用场景、使用方法、来源失败、验证方式及失效条件见各项说明。该自检不连接板卡；技能工具的通过不能代替本作品板测。技能经验摘要也不能代替原始大模型交互记录。

## 9. 当前版本一致性与提交前待办

### 已确认的代码 / 材料问题

1. **源码与部署版尚未统一。** `software/pynq/pynq_video_server.py` 与 `board/deploy/pynq_video_server.py` 的自动抓拍行为不同；源码版先保存再识别，部署版使用 `plate-confirmed-v2` 识别许可后保存。DMA 驱动也存在检查逻辑差异。当前运行按本文指定的 `board/deploy/`，提交前须确定同一正式版本并同步对应源码，再回归验证。
2. **打包目录名尚未同步。** 源目录已改名 `upload_to_jupyter_notebook/`，`scripts/upload_bundle.py` 仍输出 `upload_to_board/`。直接运行 `prepare_upload.py` 会生成旧名目录，并读取当前有差异的源码，不能视为已刷新 `board/deploy/`。先统一目录和版本，再重新打包。
3. **部署文件清单需刷新。** 当前 `board/deploy/UPLOAD_MANIFEST.json` 已没有缺失文件记录，但 `board_check/board_check.ipynb` 和其 README 的哈希与清单不一致，应在定稿时重新计算。清单完整不等于实体板已验证。
4. **外层旧构建入口与历史文件需整理。** 以 `build/rebuild.tcl` 为入口；`build/build_bd.tcl` 不按其当前位置正确解析依赖。生成缓存和重复部署 / 技能副本可在版本统一、证据留存后精简。
5. **下级旧文档需校对。** 部分 README 仍有原电脑路径、历史入口或性能占位值；执行以本根 README 的路径和入口为准，定稿时同步更新下级说明。

### 尚缺的提交材料

| 待补内容 | 建议位置 / 要求 |
|---|---|
| 定稿设计报告和对应可编辑源文件 | `report/design_report.pdf`，可附 `design_report.docx` |
| 真实大模型协作记录 | `report/ai_collaboration/`；含提示词、回答、人工核查和纠错轨迹 |
| 当前仿真原始日志 | `sim/`；区分总线双输出、Sobel、网格、ROI 和历史版别 |
| 当前三组实体板验证输出 | `board/measurements/`；记录产物版本、日期、ROI 与逐像素 / 边界核验、最终结果 |
| 实物、GUI、抓拍、识别样例与性能记录 | `board/measurements/`；包含失败场景、计时边界、样本数与环境版本 |
| 自有代码开源许可、仓库链接、第三方来源说明 | 根目录许可文件及来源说明；第三方模型的许可单独核实 |
| 干净环境复现记录 | 当前依赖表安装、模型初始化、实际识别、板端 / GUI 联调和重建的验收记录 |

截至 2026-10-30，`report/` 和外层 `sim/` 尚未放入上述材料，`board/measurements/` 尚无实测文件。源码、模型和硬件成品存在，仍需完成版本统一及交付证据补齐。
