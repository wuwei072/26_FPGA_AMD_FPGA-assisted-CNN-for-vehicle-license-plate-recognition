# PYNQ TCP 服务与 PyQt5 演示
PYNQ负责USB摄像头、FPGA双DMA、ROI抓拍和ARM对比；笔记本负责双画面显示。

## 1. 板端文件

将以下文件放在jupyter同一目录，例如 `/home/xilinx/jupyter_notebooks/fpga_edge_vision/`：

|           文件         |              用途             |
|------------------------|------------------------------|
| `pynq_video_server.py` |  板端入口，视频8080、控制8081  |
| `video_protocol.py`    |      两端共用的视频包格式      |
| `edge_dma_runtime.py`  |    缓冲复用、双DMA与3秒超时    |
| `opencv_benchmark.py`  |   按钮触发的ARM OpenCV参考算法   |
| `sobel_edge.bit` / `sobel_edge.hwh` | 配对的双DMA硬件文件 |

`validation/` 用于更换Overlay后的Golden验证。

## 2. 启动板端

通过在jupyter根目录下新建terminal板端终端运行：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_edge_vision
sudo -E python3 pynq_video_server.py --pc-ip 192.168.2.1
```

`--pc-ip` 是运行Flask车牌服务的电脑地址；默认 `192.168.2.1`。此处需要使用板上已安装PYNQ的Python环境。终端显示“等待电脑连接”后，启动电脑窗口。
抓拍默认保存在脚本所在目录，可用 `--save-dir /home/xilinx/captures` 改位置。

## 3. 电脑窗口

电脑文件在 `software/pc/`：`pc_dashboard.py`、`video_protocol.py`、`requirements.txt`。只需PyQt5。

首次在PowerShell执行：

```powershell
cd D:\fpga_edge_vision\software\pc
& D:\Plate_LPR_Server\venv\Scripts\python.exe -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe pc_dashboard.py
```

执行完后会打开PyQt5本地窗口，在左上角填写 **PYNQ板子的IPv4地址**，点击“连接 PYNQ”。默认显示 `192.168.2.99` 只是作为示例，这里要填电脑实际IP地址。

各按钮功能：
- 绿色按钮：抓拍下一处理帧的有效ROI。
- 自动抓拍开关：开启/关闭板端防抖自动抓拍。
- 黄色按钮：在板端执行一次ARM OpenCV，然后用同一帧核对FPGA六字段。
- 断开连接后可重新连接；关闭窗口会停止后台网络线程。

车牌识别使用已有电脑Flask服务：启动 `D:\Plate_LPR_Server\start_server.cmd`。

## 4. 各项指标

`FPGA+DMA window` 是驱动内部计时；`Full call` 包含输入复制与结果复制；`Call avg` 取最近60帧。ARM加速比使用同一次按需测试中同帧的耗时。候选ROI字节数 `w*h+12` 是灰度区域的理论数据量，不是JPEG大小或实际DMA传输量。
