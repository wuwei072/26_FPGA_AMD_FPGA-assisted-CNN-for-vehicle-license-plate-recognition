# PYNQ 车牌识别部署与使用

电脑运行识别服务和 PyQt5 界面，PYNQ 负责摄像头和 FPGA 处理。本说明介绍电脑识别服务的环境、模型准备与启动方法。

## 1. 准备项目和 Python

把完整项目解压到任意目录，保留原有目录结构，尤其是 `src/plate_lpr_server/models/`、`src/fpga_edge_vision/software/pc/` 和 `board/deploy/`。

从 [Python 3.12 官方下载页](https://www.python.org/downloads/release/python-31210/) 选择 **Windows installer (64-bit)**，安装时保留 pip 和 Python Launcher。安装后重新打开 CMD，检查：

```bat
py -3.12 --version
```

需要显示 `Python 3.12.x`。若提示 `No runtime installed that matches 3.12`，先执行 `py install 3.12`，完成后再检查；若 `py` 命令不存在，重新安装并启用 Python Launcher。

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

项目保留 `models/20230229/onnx/` 中的三份已解压权重：

- `y5fu_320x_sim.onnx`
- `rpv3_mdict_160_r3.onnx`
- `litemodel_cls_96x_r1.onnx`

脚本先检查这三份文件存在且非空，再配置当前 `venv` 中的 HyperLPR3 使用本地模型。权重缺失或为空时会直接报错，请恢复对应文件后再运行；脚本不会下载或解压权重。重新创建环境或重新安装 HyperLPR3 后，需要再次执行该脚本。

显示“模型准备完成”后再启动服务。

## 4. 启动电脑识别服务

在当前 CMD 中执行：

```bat
venv\Scripts\python.exe server.py
```

保持窗口打开。浏览器访问 [本机健康检查](http://127.0.0.1:5000/health)，JSON 的 `status` 应为 `ok`，`auto_save_policy` 为 `plate-confirmed-v2`。

电脑与板子用网线连接或接入同一局域网，配置为可互通的 IPv4 地址。在电脑另开 CMD 执行 `ipconfig`，记录连接板子的网卡 IPv4；在板端终端执行 `hostname -I` 查看板子 IPv4。 Windows 防火墙需允许板端访问电脑 TCP 5000，电脑需能访问板端 TCP 8080 / 8081。

## 后续操作与停止

- 电脑界面共用本目录的 `venv`，启动方法见 [客户端说明](../fpga_edge_vision/software/pc/README.md)。
- 板端文件上传、Golden 验证和视频服务启动见 [部署说明](../../board/deploy/README.md)。
- 分步验证见 [Notebook 说明](../../board/deploy/board_check/README.md)。

在本服务窗口按 `Ctrl+C` 停止。下次使用同一环境时，按第 4 节启动服务即可。
