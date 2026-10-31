# 使用步骤

电脑运行识别服务和显示窗口；PYNQ 连接 USB 摄像头并运行 FPGA 处理。
示例电脑 IP 为 `192.168.2.1`，板子 IP 为 `192.168.2.99`，使用时换成实际地址。

## 1. 电脑首次安装

安装 Python 3.12，在 Windows **CMD** 依次执行：

```bat
cd /d "D:\fpga_lpr\src\plate_lpr_server"
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe prepare_models.py
```

看到“模型准备完成”后，安装电脑显示窗口的依赖：

```bat
cd /d "D:\fpga_lpr\src\fpga_edge_vision\software\pc"
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

两个程序各用本目录的 `venv`；重新创建识别服务环境后，须再次运行 `prepare_models.py`。

## 2. 准备板端文件

把 `D:\fpga_lpr\board\deploy` 里的全部内容上传到板端
`/home/xilinx/jupyter_notebooks/fpga_edge_vision/`，保持子目录结构。
摄像头插入板子的 USB Host，电脑和板子接入同一可通信网络。

## 3. 运行 Notebook

1. 电脑双击 `D:\fpga_lpr\src\plate_lpr_server\start_server.cmd`，保持窗口打开。
2. 在板端 Jupyter 打开 `board_check/board_check.ipynb`，选择 PYNQ Python 内核。
3. 修改 `PC_IP` 和摄像头编号，从上往下逐格运行，查看图像、ROI、耗时和识别号码。
4. 未检出 ROI 或车牌不清晰时，调整目标，重跑摄像头采集、保存和识别步骤。
5. 运行“释放硬件”一格，再在 Jupyter 中 **Shutdown Kernel**。

运行前先停止板端视频服务和其他使用摄像头、DMA 的程序；报错时停止后续操作。DMA 超时需重启整板。

## 4. 启动实时视频

保持电脑识别服务运行。在板端终端执行：

```bash
cd /home/xilinx/jupyter_notebooks/fpga_edge_vision
sudo -E python3 pynq_video_server.py --pc-ip 192.168.2.1 --camera 0
```

出现“等待电脑连接”后，在电脑 CMD 执行：

```bat
cd /d "D:\fpga_lpr\src\fpga_edge_vision\software\pc"
venv\Scripts\python.exe pc_dashboard.py --host 192.168.2.99
```

点击“连接 PYNQ”，依次试双画面、手动抓拍、ARM 对比和自动抓拍。
手动图片为 `roi_*.jpg`；自动识别确认后保存为 `auto_roi_*.jpg`，默认都在板端项目目录。

## 5. 停止

关闭显示窗口，在板端服务终端按 `Ctrl+C`，再停止电脑识别服务。
连接失败先核对 IP：板端访问电脑 `5000`，电脑访问板端 `8080/8081`；同时检查服务和防火墙。
