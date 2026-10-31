# PYNQ TCP 服务与 PyQt5 演示

PYNQ负责USB摄像头、FPGA双DMA、ROI抓拍和ARM对比；笔记本负责双画面显示。

## 1. 板端文件

将以下文件放在同一目录，例如 `/home/xilinx/jupyter_notebooks/fpga_edge_vision/`：

| 文件 | 用途 |
|---|---|
| `pynq_video_server.py` | 新的板端入口，视频8080、控制8081 |
| `video_protocol.py` | 两端共用的视频包格式 |
| `edge_dma_runtime.py` | 缓冲复用、双DMA与3秒超时 |
| `opencv_benchmark.py` | 按钮触发的ARM OpenCV参考算法 |
| `sobel_edge.bit` / `sobel_edge.hwh` | 配对的双DMA硬件文件 |

`validation/` 用于更换Overlay后的Golden验证。原Notebook脚本不参与新服务运行。

## 2. 启动板端

先停止旧Dashboard，确保摄像头和DMA没有被其他程序占用。通过SSH或板端终端运行：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_edge_vision
sudo -E python3 pynq_video_server.py --pc-ip 192.168.2.1
```

`--pc-ip` 是运行Flask车牌服务的电脑地址；默认 `192.168.2.1`。此处需要使用板上已安装PYNQ的Python环境。终端显示“等待电脑连接”后，启动电脑窗口。按 `Ctrl+C` 停止服务。

抓拍默认保存在脚本所在目录，可用 `--save-dir /home/xilinx/captures` 改位置。手动抓拍直接保存无框彩色ROI。自动抓拍默认关闭，有效稳定采样累计1秒后异步识别，电脑端按识别分数不低于0.90及常见大陆7/8位号码格式筛选，明确允许自动保存后才落盘；失败或超时不保存，识别结束后冷却4秒。单帧异常暂停计时，连续异常或长间隔重新计时。关闭自动抓拍会取消尚未保存的候选结果。

## 3. 电脑窗口

电脑文件在 `software/pc/`：`pc_dashboard.py`、`video_protocol.py`、`requirements.txt`。只需PyQt5，电脑窗口不依赖PYNQ、OpenCV或Jupyter。

首次在PowerShell执行：

```powershell
cd D:\fpga_edge_vision\software\pc
& D:\Plate_LPR_Server\venv\Scripts\python.exe -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe pc_dashboard.py
```

窗口左下角填写 **PYNQ板子的IPv4地址**，点击“连接 PYNQ”。默认显示的 `192.168.2.99` 是可编辑示例，不是电脑的 `192.168.2.1`。

- 绿色按钮：抓拍下一处理帧的有效ROI。
- 自动抓拍开关：开启/关闭板端防抖抓拍。
- 黄色按钮：在板端执行一次ARM OpenCV，然后用同一帧核对FPGA六字段。
- 断开连接后可重新连接；关闭窗口会停止后台网络线程。

车牌识别继续使用已有电脑Flask服务：启动 `D:\Plate_LPR_Server\start_server.cmd`。该服务使用5000端口，与视频/控制连接独立。

本次更新需要同时重启电脑识别服务、PyQt窗口和板端服务。新版窗口只有确认板端支持新保存规则后才启用自动抓拍；显示“请更新板端服务”时，应覆盖并重启板端 `pynq_video_server.py`。旧 `fpga_edge_dashboard.py` 是历史Notebook入口，不属于当前PyQt流程。

## 4. 通信与指标

视频端口 **8080** 严格使用小端包头 `struct.Struct("<I4hfII")`，总长24字节：帧号、4个int16坐标、float32 DMA耗时、两个uint32图片长度，随后是JPEG和PNG。

控制端口 **8081** 使用UTF-8换行JSON。电脑发送 `{"command":"CAPTURE"}`、`BENCHMARK`、`AUTO_ON`、`AUTO_OFF`；板端返回带 `frame_id` 的六字段、完整调用耗时、抓拍/识别状态。视频字节流不混入JSON。

图片仍为640×480：原图JPEG质量60，单通道边缘PNG压缩1；支持时采用1-bit PNG。绿框、黄框、画中画由Qt绘制。接收线程只保留最新完整帧，窗口缩放不改变FPGA输入分辨率。

`FPGA+DMA window` 是驱动内部计时；`Full call` 包含输入复制与结果复制；`Call avg` 取最近60帧。ARM加速比使用同一次按需测试中同帧的耗时。候选ROI字节数 `w*h+12` 是灰度区域的理论数据量，不是JPEG大小或实际DMA传输量。

## 5. 硬件更换后的验证

停止视频服务后，在板端目录运行：

```bash
sudo -E python3 validation/edge_return_test.py
```

应显示三组PASS、边缘误差0、最终ALL PASS。DMA超时后按提示重启板子。

电脑刷新上传包仍用 `python scripts/prepare_upload.py`。这会从源码目录复制新服务脚本，并更新硬件产物；日常只更新Python时不必重新复制 `.bit/.hwh`。
