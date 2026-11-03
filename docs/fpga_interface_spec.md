# FPGA与PS接口规格

PL负责Sobel边缘提取、网格统计与ROI选择；PS负责摄像头采集、彩色裁剪和通信，电脑执行CNN识别。

## 1. 输入与处理规则

| 项目 | 约定 |
|---|---|
| 平台 | PYNQ-Z2，Zynq-7020（`xc7z020clg400-1`） |
| 时钟、复位 | 50 MHz；`aresetn`低有效，在时钟上升沿采样 |
| 输入 | `(480,640)`的`np.uint8`灰度图，按行从左到右传输，共307200字节 |
| 边缘 | 3×3 Sobel，`M=min(255,abs(Gx)+abs(Gy))`；`M>=80`输出255，否则0；最外圈为0 |
| 网格 | 8列×6行，每格80×80；边缘像素数严格`>768`时活跃 |
| ROI | 选择活跃格数最多的四连通区域，返回其网格外接矩形；并列时保留按行扫描首先发现的区域 |

当前阈值固定，没有PS可写的自定义配置寄存器。

## 2. AXI4-Stream接口

```text
PS灰度帧 -> 主DMA发送 -> Sobel -> 网格统计/ROI -> 主DMA接收
                            └-> 完整二值边缘图 -> 边缘DMA接收
```

| 核接口 | 方向 | 数据宽度 | 每帧有效握手／负载 | DMA连接 |
|---|---|---:|---|---|
| `s_axis_*` | 输入 | 8位 | 307200拍，307200 B | `axi_dma_0/M_AXIS_MM2S` |
| `m_axis_*` | ROI输出 | 16位 | 6拍，12 B | `axi_dma_0/S_AXIS_S2MM` |
| `edge_m_axis_*` | 边缘输出 | 8位 | 307200拍，307200 B | `axi_dma_edge/S_AXIS_S2MM` |

- 时钟上升沿`TVALID && TREADY`时传输；`TVALID=1`且`TREADY=0`时保持数据与TLAST。
- TLAST表示整帧末尾：ROI为第6字，边缘图为第307200像素；不是行末。自定义核不提供TKEEP或SOF/TUSER。
- 输入必须是固定长度完整帧，最后一拍置TLAST；RTL按像素计数分帧，不靠输入TLAST校验长度或恢复短帧。
- 两路输出独立握手，任一路阻塞都会影响后续传输，因此必须同时准备两路接收。

## 3. ROI数据包

固定6个`uint16`，共12字节，按下表顺序接收：

| 序号 | 字段 | 含义 |
|---:|---|---|
| 0 | `x` | 左上角横坐标，像素 |
| 1 | `y` | 左上角纵坐标，像素 |
| 2 | `w` | 外接矩形宽，像素 |
| 3 | `h` | 外接矩形高，像素 |
| 4 | `best_grids` | 所选区域的活跃格数，0～48 |
| 5 | `reduction_x100` | 外接矩形面积缩减百分比×100；9167表示91.67% |

有效ROI的坐标和尺寸为80的整数倍，满足`w>0`、`h>0`、`x+w<=640`、`y+h<=480`。无ROI时仍发送`[0,0,0,0,0,10000]`，没有单独的`roi_valid`字段；TVALID只表示传输有效。

面积缩减率按外接矩形计算，不能用活跃格数代替：

```text
B = (w // 80) * (h // 80)
reduction_x100 = ((48 - B) * 10000 + 24) // 48
```

PS在彩色原帧上执行`frame[y:y+h, x:x+w]`裁剪；PL返回完整边缘图与ROI坐标，不返回彩色裁剪图。

## 4. PS调用约定

| DMA实例 | PS地址窗口 | 用途 |
|---|---|---|
| `axi_dma_0` | `0x40400000`～`0x4040FFFF` | 灰度发送、ROI接收 |
| `axi_dma_edge` | `0x40410000`～`0x4041FFFF` | 边缘图接收 |

[EdgeDmaRuntime](../src/fpga_edge_vision/software/pynq/edge_dma_runtime.py)使用物理连续缓冲：输入307200个`uint8`、ROI 6个`uint16`、边缘图307200个`uint8`。调用顺序：

1. 将灰度帧复制到输入缓冲，先提交ROI接收，再提交边缘图接收。
2. 提交灰度发送，等待三个DMA通道全部完成。
3. 返回独立的六字段列表和`(480,640)`边缘数组。

默认轮询期限为3秒；传输未结束时不强制释放缓冲，需按报错提示处理。每帧实际DMA负载为614412 B，无ROI时也传完整边缘图；界面的`w*h+12`只是候选区理论数据量。

## 5. 验证与参考

Golden格式及与硬件二值图的比较规则见[测试数据](../data/README.md)。精确ROI对照使用[roi_engine_reference.py](../src/fpga_edge_vision/software/python_ref/roi_engine_reference.py)或[板端OpenCV参考](../src/fpga_edge_vision/software/python_ref/opencv_benchmark.py)；通用`cpu_reference.py`在部分等大小区域并列时的选择顺序与RTL不同。

调用计时口径见[部署说明](../board/deploy/README.md#5-通信与计时口径)。DMA与完整调用耗时均不是纯PL计算时间，也不代表摄像头、CNN和显示整条链路的延迟。

接口实现见[顶层RTL](../src/fpga_edge_vision/rtl/sobel_grid_edge_top.sv)、[构建脚本](../build/vivado/build_bd.tcl)和[配对HWH](../board/deploy/sobel_edge.hwh)；验证入口见[测试数据](../data/README.md)、[仿真说明](../sim/README.md)和[板测Notebook](../board/measurements/board_check_executed.ipynb)。
