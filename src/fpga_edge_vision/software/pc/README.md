# PyQt5 电脑客户端

客户端显示 PYNQ 彩色原图、FPGA 二值边缘图、ROI 和状态，通过 TCP 8080/8081 接收画面与发送控制。`--host` 和窗口地址栏均填写开发板 IPv4。

## 运行环境

识别服务和界面共用本项目的 `src/plate_lpr_server/venv/`。先按 [识别服务说明](../../../plate_lpr_server/README.md) 创建环境并启动电脑识别服务，再按 [部署说明](../../../../board/deploy/README.md) 启动板端视频服务。

## 启动界面

用资源管理器打开本说明所在的 `src/fpga_edge_vision/software/pc/` 文件夹，在地址栏输入 `cmd`，在该目录执行：

```bat
..\..\..\plate_lpr_server\venv\Scripts\python.exe pc_dashboard.py --host 192.168.2.99
```

将示例地址替换为板子实际 IPv4，打开窗口后点击“连接 PYNQ”。保持 `video_protocol.py` 与 `pc_dashboard.py` 位于同一目录。

## 界面显示

界面使用仿宋（`FangSong`），彩色原图和 FPGA 边缘图铺满各自的主显示区域，ROI 框按横、纵缩放比例分别映射。左侧显示彩色 ROI 画中画。

自动抓拍按钮在板端返回 `auto_capture_policy=plate-confirmed-v2` 后可用。重新启动客户端时，先关闭已有窗口，再按上述命令运行。

按钮操作、抓拍保存规则及图片位置见 [部署说明第 4 节](../../../../board/deploy/README.md#4-在电脑启动界面)。
