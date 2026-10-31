# FPGA Edge Vision

**基于 PYNQ-Z2 的实时边缘检测、动态 ROI 筛选与车牌识别演示系统**

本项目采用 Zynq-7000 的 PS + PL 架构，对 USB 摄像头画面进行硬件边缘提取和候选区域筛选，并通过电脑端 PyQt5 窗口展示原图、真实 FPGA 边缘图和 ROI。在车牌演示场景中，板端裁剪彩色 ROI，通过 HTTP 调用电脑上的识别服务，完成抓拍、识别与结果反馈。

FPGA 负责 **Sobel、网格边缘统计和四连通最大区域选择**；摄像头采集、彩色裁剪与服务调度运行在 ARM 上，车牌检测与识别模型运行在电脑上。

**English:** A PYNQ-Z2 hardware/software vision system with RTL Sobel filtering, grid-based ROI selection, dual-DMA edge return, a PyQt5 dashboard, and asynchronous PC-side license plate recognition.

[系统架构](#系统架构) · [演示功能](#演示功能) · [目录结构](#目录结构) · [软硬件环境](#软硬件环境) · [快速开始](#快速开始) · [从源码构建](#从源码构建) · [算法与接口](#算法与接口) · [性能与验证](#性能与验证) · [使用边界](#使用边界) · [文档导航](#文档导航)

## 项目特点

- **流式 RTL 图像处理**：对 640×480、8-bit 灰度帧完成 3×3 Sobel、阈值二值化、8×6 网格统计与 ROI 筛选。
- **双 DMA 结果回传**：同时获取 12 B ROI 元数据和 307200 B 二值边缘图，支持逐像素核验。
- **电脑端实时展示**：PyQt5 双画面、ROI 框与画中画，支持连接、断开和重连。
- **同帧 ARM 对比**：按需运行板端 OpenCV 参考算法，核对同一帧的六个 ROI 字段并显示耗时。
- **手动与自动抓拍**：手动保存有效 ROI；自动模式结合稳定性判断、异步识别确认和冷却机制。
- **软硬件验证配套**：提供 Python 参考模型、Golden vectors、RTL testbench 和板端验证脚本。

## 系统架构

![PYNQ-Z2 与电脑端系统架构](docs/figures/method_draw_http_roi_edited.png)

| 层级 | 主要职责 |
|---|---|
| PYNQ-Z2 PS / ARM | USB 摄像头采集、灰度转换、DMA 调度、彩色 ROI 裁剪、抓拍、OpenCV 对比、异步 HTTP 请求 |
| PYNQ-Z2 PL / FPGA | Sobel 边缘提取、二值化、网格统计、活跃网格判断、四连通最大区域选择 |
| 电脑 PyQt5 | 双画面展示、ROI 框与画中画、按钮控制、同帧指标与识别状态展示 |
| 电脑 Flask 识别服务 | 车牌检测与识别，返回识别结果及自动保存许可 |

硬件数据通路：

`PS DDR → axi_dma_0 MM2S → Sobel → 网格统计 / ROI → axi_dma_0 S2MM（12 B）`

Sobel 的二值边缘流另经 `axi_dma_edge S2MM` 回传整幅边缘图（307200 B）。当前主线 Overlay 为 **50 MHz 双 DMA 版本**，文件名为 `sobel_edge.bit / sobel_edge.hwh`。

| 连接 | 端口 | 内容 |
|---|---:|---|
| 板端 → PyQt5 | TCP 8080 | 帧号、ROI、DMA 耗时，以及彩色 JPEG 和二值边缘 PNG |
| PyQt5 ↔ 板端 | TCP 8081 | 换行 JSON：抓拍、自动模式、ARM 测试命令及同帧指标、状态 |
| 板端 → 电脑识别服务 | HTTP 5000 | 彩色 ROI 识别请求，接口为 `/api/recognize` |

## 演示功能

### 双画面与运行指标

电脑窗口显示原始彩色画面和 FPGA 返回的二值边缘图，并绘制 ROI 框与局部画中画。界面展示 ROI 坐标、活跃网格数、面积缩减率和处理耗时。

- `FPGA+DMA window`：驱动内部记录的硬件处理与 DMA 等待窗口。
- `Full call`：包含输入复制与结果复制的完整驱动调用耗时。
- `Call avg`：最近 60 帧完整调用的平均耗时。
- ARM 对比：点击按钮后，在板端用同一灰度帧执行 OpenCV 参考算法，比较六字段与耗时。

### 手动抓拍与车牌识别

点击抓拍按钮后，板端保存下一处理帧的有效彩色 ROI，图片不含界面叠加框，并异步提交给电脑端识别服务。识别状态经控制连接回传到窗口。

识别服务是独立的电脑端项目；本目录提供图像处理、展示和调用接口，服务启动方法见下方“启用车牌识别”。

### 稳定目标自动抓拍

自动抓拍默认关闭。开启后，有效且稳定的 ROI 累计约 **1 秒**再触发异步识别；只有识别服务明确允许自动保存时才落盘。当前配套规则要求识别分数不低于 **0.90**，并符合常见大陆 7/8 位车牌格式。

单帧异常暂停累计，连续异常或采样间隔过长会重新计时；识别失败或超时不自动保存，任务结束后冷却 **4 秒**。关闭自动模式会取消尚未保存的候选结果。

板端需声明 `plate-confirmed-v2` 规则，窗口确认支持后才启用自动抓拍。流程图见 [自动抓拍稳定判定与调度](docs/figures/auto_capture_stability_cn.png)。

## 目录结构

```text
fpga_edge_vision/
├── README.md
├── docs/                           # 接口规格、部署说明、架构图与开发记录
│   └── figures/                    # 系统架构与自动抓拍流程图
├── hardware/
│   ├── rtl/                        # Sobel、网格统计、ROI、流复制与顶层 RTL
│   ├── sim/                        # Testbench、raw 向量及仿真日志
│   └── vivado/sobel_edge_system/
│       ├── build_bd.tcl             # 双 DMA 系统构建入口
│       └── output/                 # .bit/.hwh、时序与资源报告
├── software/
│   ├── pynq/                       # 板端视频服务、DMA 驱动和验证源码
│   ├── pc/                         # PyQt5 客户端、协议与依赖
│   ├── python_ref/                 # CPU 参考模型、OpenCV 对比与冻结测试
│   ├── python/                     # 早期软件参考实现
│   └── tests/                      # 早期参考实现测试
├── data/
│   ├── input/                      # 输入测试图
│   └── golden_vectors/             # 固定功能基准 PGM / JSON
├── scripts/                        # 上传包整理等工具
├── upload_to_board/                # 可上传到板端的部署文件
│   ├── validation/                 # 双 DMA Golden 验证脚本与向量
│   └── board_check/                # 分模块诊断 Notebook 与复测手册
├── results/                        # 参考结果、构建辅助结果及 ROI-only 回退文件
├── report/figures/                 # 报告插图
└── skill/                          # 调试与验证工作流说明
```

正式演示入口为板端 `pynq_video_server.py` 和电脑端 `pc_dashboard.py`。目录中的 `fpga_edge_dashboard.py` 为历史 Notebook 演示入口。

## 软硬件环境

### 硬件

| 硬件 | 用途 |
|---|---|
| PYNQ-Z2（Zynq-7020，`xc7z020clg400-1`） | 运行 PYNQ 与 FPGA Overlay |
| 写入 PYNQ 镜像的 Micro SD 卡、适配电源 | 板端启动与供电 |
| USB 摄像头 | 插入开发板 USB Host 口，提供画面 |
| 网线与电脑 | 板端通信、PyQt5 展示及可选识别服务 |

### 软件

| 环境 | 依赖或要求 |
|---|---|
| 板端 | PYNQ Python 环境、`pynq`、NumPy、OpenCV；摄像头可由 OpenCV 打开 |
| 电脑展示端 | Python 3、`PyQt5==5.15.11`；依赖见 [requirements.txt](software/pc/requirements.txt) |
| 电脑识别端（可选） | 兼容 `/api/recognize` 的 Flask 车牌服务及其模型环境，独立部署 |
| 硬件重建 | Vivado **2025.1**、PYNQ-Z2 board files |
| 位精确 CPU 参考模型 | Python 标准库，无强制第三方依赖 |

PyQt5 窗口本身只需 PyQt5。PYNQ、OpenCV 与模型推理由各自运行端提供。现有构建产物可直接部署；修改 RTL 或 Block Design 后需要重新构建。

## 快速开始

以下以工程位于 `D:\fpga_edge_vision`、板端目录为 `/home/xilinx/jupyter_notebooks/fpga_edge_vision` 为例，实际使用时替换路径和 IP。

### 1. 准备板端与网络

1. 启动 PYNQ-Z2，将 USB 摄像头插入板端 USB Host 口，接通电脑与板子的网络。
2. 确认双方 IPv4 地址。本文用电脑 `192.168.2.1`、板子 `192.168.2.99` 举例。
3. 停止旧视频服务或 Notebook Dashboard，释放摄像头和 DMA。
4. 将 `upload_to_board/` 中的部署文件上传到板端同一目录，保留 `validation/` 子目录。

板端主要文件为：

```text
pynq_video_server.py
video_protocol.py
edge_dma_runtime.py
opencv_benchmark.py
sobel_edge.bit
sobel_edge.hwh
validation/
```

`.bit` 和 `.hwh` 必须来自同一次构建、同名配对。若改过源码，先在电脑工程根目录运行 `python scripts/prepare_upload.py` 刷新上传包；该命令会同步部署脚本和硬件产物，打包成功后仍需板端验证。

### 2. 验证 Overlay

首次部署或更换硬件文件后，先在板端终端执行：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_edge_vision
sudo -E python3 validation/edge_return_test.py
```

验收条件为三组向量均 `PASS`、边缘像素误差和非零边界数均为 `0`，最终显示 `ALL PASS`。测试结束后再启动视频服务；DMA 超时后按提示重启板子。

### 3. 启动板端服务

```bash
cd /home/xilinx/jupyter_notebooks/fpga_edge_vision
sudo -E python3 pynq_video_server.py --pc-ip 192.168.2.1
```

使用板上已安装 PYNQ 的 Python 环境。`--pc-ip` 填运行识别服务的**电脑 IP**；可通过 `--camera 0` 指定摄像头，通过 `--save-dir /home/xilinx/captures` 指定抓拍目录。默认保存到服务脚本所在目录。

### 4. 启动电脑窗口

首次在 PowerShell 创建环境并安装依赖：

```powershell
cd D:\fpga_edge_vision\software\pc
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe pc_dashboard.py
```

`python` 需指向可用的 Python 3；也可用已有 Python 解释器的完整路径创建环境。之后直接运行最后一条命令即可。

在窗口中填写 **PYNQ 板子的 IP** 并点击“连接 PYNQ”。电脑需能访问板端 TCP 8080、8081。

### 5. 启用车牌识别（可选）

当前配套电脑服务位于独立目录，可启动：

```powershell
& D:\Plate_LPR_Server\start_server.cmd
```

服务需在电脑 5000 端口提供 `POST /api/recognize`，板端 `--pc-ip` 应与这台电脑的地址一致。迁移到其他电脑时，需要另外部署识别服务与模型；其源码和模型不包含在本工程中。

完整步骤与自动保存规则见 [部署说明](upload_to_board/README.md)，分模块排查见 [板端复测手册](upload_to_board/board_check/README.md)。

## 从源码构建

### Vivado 硬件构建

安装 PYNQ-Z2 board files 后，在 Vivado 2025.1 Tcl Console 执行：

```tcl
cd D:/fpga_edge_vision/hardware/vivado/sobel_edge_system
source ./build_bd.tcl
```

也可在已配置 Vivado 环境的终端中，进入该目录执行 `vivado -mode batch -source build_bd.tcl`。脚本会重新生成当前 `project/` 与 `output/` 的构建产物，输出包括：

```text
output/sobel_edge.bit
output/sobel_edge.hwh
output/address_map_vivado.txt
output/timing_summary.rpt
output/utilization.rpt
```

图像处理逻辑由 SystemVerilog / Verilog RTL 实现。仿真顶层、依赖文件与向量参数见 [硬件说明](hardware/vivado/sobel_edge_system/README.md)；当前双输出 testbench 为 `hardware/sim/tb_sobel_grid_edge_top.sv`。

### CPU 参考与接口冻结测试

从工程根目录运行：

```powershell
python -m unittest discover -s software/python_ref -p "test_*.py" -v
```

测试覆盖参考模型和冻结接口行为。需要重新生成参考输出时可运行 `python software/python_ref/cpu_reference.py`；重新生成 Golden vectors 的方法见 [参考模型说明](software/python_ref/readme.md)。

## 算法与接口

| 项目 | 当前规格 |
|---|---|
| 输入 | 640×480、8-bit 灰度，行优先，共 307200 B |
| Sobel | 3×3，幅值 `min(255, abs(Gx)+abs(Gy))`，最外圈清零 |
| 二值边缘 | 幅值 `>=80` 输出 255，否则 0 |
| 网格 | 8 列 × 6 行，每格 80×80，共 48 格 |
| 活跃条件 | 每格 `edge_count > 768`，即边缘占比严格大于 12% |
| 区域选择 | 四连通，选活跃网格数最多的区域；并列时保留先按行扫描到的区域 |
| ROI | 所选区域的网格包围框，坐标按 80 像素量化 |
| ROI 回传 | 6 个 `uint16`：`x, y, width, height, best_grids, reduction_x100`，共 12 B |
| 边缘回传 | 640×480、uint8 二值图，共 307200 B |
| 缩减率 | `round((307200-width*height)*10000/307200)`；`9167` 表示 91.67% |
| 无有效区域 | 前五字段为 0，`reduction_x100=10000` |

灰度候选 ROI 的理论字节数为 `width*height+12`。当前双 DMA 演示仍会回传完整边缘图，面积缩减率用于描述候选区域大小；实际 DMA、TCP 和 JPEG 数据量需分别统计。

完整算法约定见 [FPGA 接口规格](docs/fpga_interface_spec.md)。该文档中的 `roi_valid` 是逻辑有效性描述，当前 DMA 的六字段数据包不单独携带此字段。

## 性能与验证

### 当前双 DMA 实现结果

以下数据来自 **2026-10-23、Vivado 2025.1、布局布线后的 50 MHz 双 DMA 系统**，包含处理系统接口、DMA 与互连等 PL 逻辑。

| 资源 | 使用量 | 器件总量 | 占比 |
|---|---:|---:|---:|
| LUT | 5044 | 53200 | 9.48% |
| FF | 6768 | 106400 | 6.36% |
| Block RAM Tile | 5.5 | 140 | 3.93% |
| DSP | 0 | 220 | 0% |

| 时序指标 | 结果 |
|---|---:|
| PL 时钟 | 50 MHz |
| Setup WNS / Hold WHS | +10.360 ns / +0.020 ns |
| TNS / THS | 0 ns / 0 ns |
| Setup / Hold 失败端点 | 0 / 0 |

满足报告中的用户时序约束。原始报告：[资源利用率](hardware/vivado/sobel_edge_system/output/utilization.rpt)、[时序汇总](hardware/vivado/sobel_edge_system/output/timing_summary.rpt)。

### Golden 验证基准

板端验证脚本使用以下三组固定向量，检查六个 ROI 字段及每一幅二值边缘图：

| 向量 | 期望六字段 `x, y, width, height, best_grids, reduction_x100` |
|---|---|
| 单目标 | `160, 160, 160, 160, 4, 9167` |
| 多目标 | `80, 80, 240, 160, 6, 8750` |
| 带噪声目标 | `400, 160, 160, 160, 4, 9167` |

这是验收基准；当前目录未保存本版双 DMA 的完整板测输出，现场结果应以 `validation/edge_return_test.py` 的运行记录为准。

### 现场性能：示例占位，非实测

> **以下数值仅用于 README 排版占位，均非实测结果，也不代表性能预期。待晚间上板测试后逐项替换；对外展示或提交前应删除示例值或补入真实记录。**

| 指标 | 示例占位值（非实测） | 替换时记录 |
|---|---:|---|
| 电脑实时显示帧率 | 12.0 FPS（示例） | 场景、测试时长、平均 / 最低 FPS |
| FPGA+DMA window | 25.0 ms（示例） | 同帧驱动内部计时 |
| Full call | 28.0 ms（示例） | 含输入与结果复制的完整调用 |
| ARM OpenCV | 50.0 ms（示例） | 同一帧、同一算法输出约定 |
| ARM / FPGA Full call 耗时比 | 1.79×（示例计算） | `ARM OpenCV / Full call`，六字段匹配时比较 |
| 功耗 | 待测 | 测量方式、整板或芯片范围、运行状态 |
| 车牌识别统计 | 待统计 | 样本数、场景及成功判据 |

示例耗时比由 `50.0/28.0` 四舍五入得到。以上现场性能示例与前面的 **Vivado 真实资源、时序结果**分开记录。

实测时应注明 Overlay 版本、时钟、输入与样本数。驱动耗时与显示帧率包含的环节不同；纯 Python 参考模型和 OpenCV 参考算法也应分别标注，便于比较。

## 使用边界

- ROI 根据边缘密度选择，复杂纹理背景也可能被选中；车牌类别由电脑端模型进一步判断。
- “动态 ROI”表示候选区域随画面变化；当前二值阈值 80、网格阈值 768 均固定。
- 网格为 80×80，候选框较粗，单帧仅保留最大连通区域。PCB、密集文字、条码等边缘丰富的对象也适合演示；纯色或纹理稀少的物体可能无法触发活跃网格。
- CNN 检测与识别运行在电脑端。自动保存依赖配套识别服务返回许可，失败或超时不保存。
- 更新脚本后需重启对应服务。硬件回退文件 `results/roi_only_fallback/sobel.bit / sobel.hwh` 仅供 ROI-only 方案使用，当前双 DMA 服务需要 `sobel_edge.bit / sobel_edge.hwh`。

## 文档导航

| 文档 | 内容 |
|---|---|
| [部署说明](upload_to_board/README.md) | 板端文件、启动步骤、通信协议、自动保存规则 |
| [板端复测手册](upload_to_board/board_check/README.md) | 网络、摄像头、DMA、显示、识别的分模块诊断 |
| [电脑客户端](software/pc/README.md) | PyQt5 环境与连接方式 |
| [硬件说明](hardware/vivado/sobel_edge_system/README.md) | RTL 仿真与双 DMA 构建 |
| [FPGA 接口规格](docs/fpga_interface_spec.md) | 算法、边界、阈值、网格与 ROI 验收约定 |
| [CPU 参考模型](software/python_ref/readme.md) | 软件基准、测试与结果生成 |
| [Golden vectors](data/golden_vectors/readme.md) | 固定测试图与期望结果 |
