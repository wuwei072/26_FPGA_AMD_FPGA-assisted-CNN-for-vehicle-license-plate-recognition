# PYNQ TCP 服务与 PyQt5 演示

PYNQ-Z2 连接 USB 摄像头，完成 FPGA 双 DMA 处理、彩色 ROI 抓拍和 ARM OpenCV 对照；电脑运行 HyperLPR3 识别服务与 PyQt5 双画面界面。本说明随板端部署目录提供。

## 1. 准备文件、设备与地址

电脑代码位于完整项目的 `src/plate_lpr_server/` 和 `src/fpga_edge_vision/software/pc/`。将项目 `board/deploy/` 中的全部内容上传至板端同一个目录，例如 `/home/xilinx/jupyter_notebooks/fpga_edge_vision/`，保留子目录及文件名：

| 文件或目录 | 用途 |
|---|---|
| `pynq_video_server.py` | 板端入口，视频 TCP 8080、控制 TCP 8081 |
| `video_protocol.py` | 视频包格式 |
| `edge_dma_runtime.py` | 双 DMA 调度、缓冲管理与超时检查 |
| `opencv_benchmark.py` | 同帧 ARM OpenCV 参考算法 |
| `sobel_edge.bit` / `sobel_edge.hwh` | 配对的 50 MHz 双 DMA 硬件文件 |
| `validation/` | Golden 验证脚本与完整输入、期望向量 |
| `board_check/` | 分模块检查 Notebook 与使用说明 |
| `upload_manifest.json` | 部署文件清单 |

板子需已启动可导入 PYNQ、NumPy、OpenCV 的 PYNQ 镜像，摄像头接 USB Host。电脑安装 Python 3.12（64 位），双方网络互通。

| 使用位置 | 填写哪个 IPv4 地址 |
|---|---|
| 板端视频服务 `--pc-ip` | 运行识别服务的电脑 |
| 电脑界面地址栏或 `--host` | PYNQ 板子 |
| Notebook `PC_IP` | 运行识别服务的电脑 |

下文 `192.168.2.1` 为电脑地址示例，`192.168.2.99` 为板子地址示例，使用时替换为实际值。电脑可在 CMD 执行 `ipconfig`，板端终端执行 `hostname -I` 查看地址。

## 2. 在电脑准备环境并启动识别服务

按随包 [Notebook 说明第 1 节](board_check/README.md#1-先在电脑准备识别服务) 在电脑的完整项目中创建环境、准备模型并启动识别服务。确认健康检查通过后，保持该服务窗口运行，再进行板端验证。

## 3. 在板端验证并启动视频服务

先结束占用摄像头或 DMA 的其他任务。若运行过 Notebook，先执行 [board_check.ipynb](board_check/board_check.ipynb) 第 8 节释放硬件，保存并 **Shutdown Kernel**。然后在 PYNQ Jupyter 中打开 Terminal，进入实际上传目录；以下使用第 1 节的板端路径示例：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_edge_vision
sudo -E python3 -c "import pynq, cv2, numpy; print('板端依赖正常')"
sudo -E python3 validation/edge_return_test.py
```

使用板上可导入 PYNQ 的 Python 环境，不在板端安装电脑的 `requirements.txt`。三组 Golden 验证均为 `PASS`、边缘误差与非零边界数均为 0、最终显示 `ALL PASS` 后，启动：

```bash
sudo -E python3 pynq_video_server.py --pc-ip 192.168.2.1 --camera 0
```

将 `--pc-ip` 替换为电脑实际 IPv4，不能填 `127.0.0.1`；`--camera` 按摄像头编号调整。看到“等待电脑连接”后保持终端运行。更换 Overlay 后应重新验证，`.bit/.hwh` 必须同名配对并与所用驱动匹配。DMA 超时按程序提示重启板子，再从 Golden 验证开始。

若先运行分模块检查，按 `board_check/README.md` 操作；Notebook 与视频服务不能同时占用摄像头和 DMA。

## 4. 在电脑启动界面

在电脑完整项目的 `src/plate_lpr_server/` 另开 CMD，执行：

```bat
venv\Scripts\python.exe "..\fpga_edge_vision\software\pc\pc_dashboard.py" --host 192.168.2.99
```

把 `--host` 换成板子实际 IPv4；界面中的地址同样填写板子 IPv4，点击“连接 PYNQ”。确认彩色原图和 FPGA 边缘图更新，再检查以下功能：

- 手动抓拍：直接保存下一处理帧的有效、无叠加框彩色 ROI，然后异步请求电脑识别。文件名为 `roi_*.jpg`，识别失败不删除已保存的手动图片。
- 自动抓拍：默认关闭。开启后，有效 ROI 稳定累计约 1 秒时，先将候选彩色 ROI 异步发给电脑识别；仅当返回识别成功、非空车牌号码且 `auto_save_allowed=true` 时，才保存 `auto_roi_*.jpg`。未识别、异常或超时不保存自动候选，任务结束后冷却约 4 秒。单次异常暂停稳定累计；连续异常或间隔过长会重新累计。关闭自动抓拍会取消尚未保存的候选结果。
- ARM 对照：按按钮后，对同一灰度帧计算 OpenCV 参考结果，核对 FPGA 六字段与耗时。

图片默认保存在板端视频服务脚本所在目录，可通过 `--save-dir /home/xilinx/captures` 改位置。电脑识别服务当前以置信分数不低于 0.90、常见大陆 7/8 位号码格式筛选识别结果；候选 ROI 本身不保证包含车牌。更新程序后重启两端对应服务，保持电脑和板端规则匹配。

## 5. 通信与计时口径

视频端口 **8080** 使用小端包头 `struct.Struct("<I4hfII")`，共 24 字节：帧号、4 个 int16 坐标、float32 DMA 耗时、两个 uint32 图片长度，后接彩色 JPEG 和二值边缘 PNG。

控制端口 **8081** 使用 UTF-8 换行 JSON。电脑发送 `CAPTURE`、`BENCHMARK`、`AUTO_ON`、`AUTO_OFF` 命令；板端返回 `frame_id`、六字段、完整调用耗时、抓拍与识别状态。电脑识别服务通过 **HTTP 5000** 的 `POST /api/recognize` 接收 JPEG。

输入为 640×480。彩色 JPEG 质量为 60，边缘 PNG 压缩级别为 1；支持时使用 1-bit PNG，二值像素仍为 0/255。界面叠加框和画中画由 Qt 绘制。

`FPGA+DMA window` 是驱动内部计时，`Full call` 包含输入和结果复制，`Call avg` 为最近最多 60 帧完整调用均值。ARM/FPGA 耗时比应使用同帧结果一致的测试记录。`w*h+12` 是灰度候选 ROI 的理论字节数；当前双 DMA 还回传完整边缘图，面积缩减率不能直接代替实际 DMA、TCP 数据量或显示帧率。

## 6. 停止与再次启动

关闭电脑界面；在板端视频服务和电脑识别服务的终端各按 `Ctrl+C`。以后按“电脑识别服务 → 板端视频服务 → 电脑界面”的顺序启动。代码更新后重启对应程序；硬件文件更新后先重新运行 Golden 验证。
