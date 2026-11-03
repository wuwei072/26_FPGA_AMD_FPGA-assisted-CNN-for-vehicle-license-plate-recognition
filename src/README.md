# 源码目录

`src` 下包含 FPGA 视觉处理工程和电脑端车牌识别服务：

```text
src/
├── fpga_edge_vision/       FPGA 视觉处理工程
│   ├── rtl/               底层硬件代码
│   ├── software/          板端程序、PyQt5 界面和 Python 参考模型
└── plate_lpr_server/      电脑识别服务、模型、依赖清单和运行说明
```

安装和运行步骤见 [车牌识别部署说明](plate_lpr_server/README.md)，项目整体介绍见 [根目录 README](../README.md)。

硬件入口见 [build/rebuild.tcl](../build/rebuild.tcl)，仿真与测试数据见 [仿真说明](../sim/README.md) 和 [数据说明](../data/README.md)。
