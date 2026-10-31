# PYNQ 车牌识别部署与使用

电脑运行识别服务和 PyQt5 界面，PYNQ 负责摄像头和 FPGA 处理。首次部署按下面顺序完成，之后只需启动三个程序。

## 1. 准备项目和 Python

把完整项目解压到任意目录，保留原有目录结构，尤其是 `src/plate_lpr_server/models/`、`src/fpga_edge_vision/software/pc/` 和 `board/deploy/`。

在电脑上安装 [Python 3.12 的 Windows 64 位安装包]。安装后重新打开 CMD，检查：

```bat
py -3.12 --version
```

应显示 `Python 3.12.x`。若提示 `No runtime installed that matches 3.12`，先执行 `py install 3.12`，完成后再检查；若 `py` 命令不存在，重新安装并启用 Python Launcher。

## 2. 在项目内创建环境

用资源管理器打开项目中的 `src/plate_lpr_server` 文件夹，在地址栏输入 `cmd` 并回车。下文的电脑命令都在这个目录执行。

如果这里已有从其他位置复制或用旧项目 Python 创建的 `venv`，先关闭相关程序，将它改名为 `venv_old` 等未使用的名称，再创建新环境：

```bat
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pip check
```

依赖包括 PyQt5、Flask、HyperLPR3、ONNX Runtime、NumPy 和 OpenCV。`pip check` 应显示 `No broken requirements found.`。后续命令都使用这里的 `venv\Scripts\python.exe`。

检查环境位置和界面依赖：

```bat
venv\Scripts\python.exe -c "import sys; from PyQt5 import QtWidgets, QtSvg; print(sys.executable); print('依赖正常')"
```

输出的解释器路径应在当前项目的 `src/plate_lpr_server/venv/` 中。部署成功后保留这个 `venv` 和用于创建它的已安装 Python。

## 3. 初始化模型

在同一个 CMD 中执行：

```bat
venv\Scripts\python.exe prepare_models.py
```
## 4. 启动电脑识别服务

然后在当前 CMD 中执行，也可以双击本目录的启动脚本：

```bat
start_server.cmd
```

保持窗口打开。浏览器访问 [本机健康检查](http://127.0.0.1:5000/health)，应返回 `"status":"ok"`。

电脑与板子用网线连接或接入同一局域网，配置为可互通的 IPv4 地址。在电脑另开 CMD 执行 `ipconfig`，记录连接板子的网卡 IPv4；在板端终端执行 `hostname -I` 查看板子 IPv4。

## 5. 部署并启动板端

PYNQ-Z2 需已启动匹配的 PYNQ 镜像，并能进入 Jupyter。USB 摄像头接在板子的 USB Host 上。

将项目 `board/deploy/` 中的全部内容上传到板端同一个目录，保留子目录及文件名，包括 `pynq_video_server.py`、`video_protocol.py`、`edge_dma_runtime.py`、`opencv_benchmark.py`、配对的 `sobel_edge.bit` / `sobel_edge.hwh` 和完整 `validation/`。

先结束板端其他占用摄像头或 FPGA 的任务。在 Jupyter 中打开 Terminal，进入实际上传目录。下面的 `实际上传目录` 和 `电脑IPv4地址` 都要替换成自己的值；这里使用板上可导入 PYNQ 的 Python，不安装电脑端的 `requirements.txt`：

```bash
cd "实际上传目录"
sudo -E python3 -c "import pynq, cv2, numpy; print('板端依赖正常')"
sudo -E python3 validation/edge_return_test.py
```

验证最后显示 `ALL PASS` 后启动视频服务：

```bash
sudo -E python3 pynq_video_server.py --pc-ip 电脑IPv4地址 --camera 0
```

`--pc-ip` 填运行识别服务的电脑地址，不能填 `127.0.0.1`；`--camera 0` 按实际摄像头编号调整。看到“等待电脑连接”后保持终端运行。若提示 DMA 超时，重启板子后重新验证。

## 6. 启动电脑界面

再次用资源管理器打开项目中的 `src/plate_lpr_server`，在地址栏输入 `cmd`，另开一个窗口执行：

```bat
venv\Scripts\python.exe "..\fpga_edge_vision\software\pc\pc_dashboard.py"
```

在界面中填写板子的 IPv4，点击连接。确认原图和 FPGA 边缘图正常更新，再点击抓拍，检查车牌识别结果。抓拍文件保存在板端视频脚本所在目录。

## 日常使用

以后按“电脑识别服务 → 板端视频服务 → 电脑界面”的顺序启动，无需重复安装依赖或初始化模型。关闭界面可退出客户端；板端视频服务按 Ctrl+C 停止；电脑识别服务按 Ctrl+C 或双击 `stop_server.cmd` 停止。
