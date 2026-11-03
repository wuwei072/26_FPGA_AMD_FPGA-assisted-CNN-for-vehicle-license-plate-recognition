# 板端分模块检查与实时演示

此目录中的 `board_check.ipynb` 在 **PYNQ 板端 Jupyter** 运行。电脑运行识别服务和显示界面。Notebook 模板包含9个代码单元，按文档和单元说明从上往下运行。

## 1. 先在电脑准备识别服务

在完整项目的 `src/plate_lpr_server/` 中，用资源管理器地址栏输入 `cmd` 打开 CMD。安装 Python 3.12（64 位），确认 `py -3.12 --version` 正常。下面几行指令请先等一行执行完后再复制执行下一行，否则可能会下载遗漏难以查找。若已有从其他位置复制的 `venv`，先停止相关程序、改名并重新创建：

```bat
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pip check
venv\Scripts\python.exe prepare_models.py
venv\Scripts\python.exe server.py
```

识别服务要求使用当前 `src/plate_lpr_server/venv/`；它也包含电脑界面依赖。重新创建环境后，须再次运行 `prepare_models.py`。保持服务窗口打开，电脑浏览器访问 `http://127.0.0.1:5000/health`，JSON 的 `status` 应为 `ok`，`auto_save_policy` 为 `plate-confirmed-v2`。

## 2. 准备板端文件和地址

将完整项目 `board/deploy/` 的全部内容上传至板端同一个目录，例如 `/home/xilinx/jupyter_notebooks/fpga_edge_vision/`，保持 `validation/`、本 `board_check/` 和 `.bit/.hwh` 等文件的相对位置。USB 摄像头接板子 USB Host，板端镜像应提供 PYNQ、OpenCV、NumPy。

电脑 `ipconfig` 查看运行识别服务的网卡 IPv4，板端 `hostname -I` 查看板子 IPv4。示例电脑 `192.168.2.1`、板子 `192.168.2.99` 均须替换成实际地址。板端访问电脑 TCP 5000；电脑访问板端 TCP 8080 / 8081。

## 3. 逐格运行 Notebook

1. 停止板端视频服务和其他占用摄像头、DMA 的任务。
2. 在板端 Jupyter 打开本目录 `board_check.ipynb`，选择可导入 PYNQ 的 Python 内核。
3. 将 `PC_IP` 改成电脑 IPv4、`CAMERA_INDEX` 改成实际摄像头编号，从上往下逐格运行。
4. 检查三组标准图和空白帧的 ROI、边缘误差与同帧耗时；再采集摄像头、手动保存彩色 ROI 并向电脑请求识别。未得到有效 ROI 或车牌不清晰时，调整目标后重跑相应步骤。
5. 运行“释放硬件”单元，在 Jupyter 中保存 Notebook 并 **Shutdown Kernel**，再切换到完整实时链路。

Notebook 的第 5 步直接保存手动 ROI，第 7 步再请求识别；这组分步操作与实时服务的自动识别后保存流程分开。报错时先排查当前步骤；DMA 超时按程序提示重启整板后重新验证。

## 4. 启动实时视频

完成本说明第 3 节后，保持电脑识别服务运行，并按上级部署说明的 [第 3 节](../README.md#3-在板端验证并启动视频服务) 和 [第 4 节](../README.md#4-在电脑启动界面) 启动板端视频服务与电脑界面。

## 5. 停止

按上级部署说明的 [第 6 节](../README.md#6-停止与再次启动) 停止界面和两端服务。

## 保存验证记录
以下步骤用于归档板端运行输出与 ROI 图片，便于结果复核。
执行后先保存，再用 `File → Download as → Notebook (.ipynb)` 下载，另存到电脑项目 `board/measurements/board_check_executed.ipynb`。第 5 节打印的 ROI 图片可一并下载到该目录。
复现时打开本 `board/deploy/board_check/board_check.ipynb` 模板。电脑本地文件更新后，需要重新上传板端同名 Notebook 并重新打开，板上旧文件不会自动同步。
