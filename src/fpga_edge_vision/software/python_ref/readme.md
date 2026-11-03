# 软件参考模型与验证

| 文件 | 用途 |
|---|---|
| `cpu_reference.py` | PGM 读写、Sobel、网格四连通 ROI、Golden 生成及像素级诊断 |
| `roi_engine_reference.py` | 读取 48 项网格计数，以位图扩张模拟 RTL 的 ROI 模块 |
| `opencv_benchmark.py` | 板端按需处理同一帧，生成 OpenCV ROI 六字段与二值边缘图 |
| `test_cpu_reference.py` | 基础图像、网格、ROI 和输出测试 |
| `test_fpga_freeze.py` | 冻结契约、边界、连通性、最大区域及 Golden 可重复性测试 |

## 离线测试

从仓库根目录执行：

```powershell
py -3.12 -B -m unittest discover -s src/fpga_edge_vision/software/python_ref -p 'test_*.py' -v
py -3.12 -B src/fpga_edge_vision/software/python_ref/roi_engine_reference.py
```

测试在临时目录生成中间数据，不连接开发板或调用 CNN；通过不代表实体板验证通过。ROI 模块参考读取 `data/hdl_vectors/*_grid_counts.hex`。输入、Golden 和格式见[测试数据说明](../../../../data/README.md)。

像素级八连通路径仅用于诊断。主线算法及通用 CPU 参考与 RTL 的并列选择差异见[接口规格](../../../../docs/fpga_interface_spec.md)。

## 参考结果与 Golden 生成

`cpu_reference.py` 默认读取 `data/input/`，写入 `data/reference_results/`。已有历史结果无需为部署重新生成；需要新结果时可指定独立目录：

```powershell
py -3.12 -B src/fpga_edge_vision/software/python_ref/cpu_reference.py --results build/local_reference_results
```

输入目录为空时，程序会生成三张确定性的 640×480 示例图。以下命令会覆盖 `data/golden_vectors/` 中的冻结基准，仅在核查算法变更后使用；正常验证运行上方测试即可：

```powershell
py -3.12 -B src/fpga_edge_vision/software/python_ref/cpu_reference.py --write-golden-vectors
```

## 依赖与运行位置

`cpu_reference.py`、`roi_engine_reference.py` 和两个 `test_*.py` 仅使用 Python 标准库，使用 Python 3.12 可执行，无需 NumPy、OpenCV、PYNQ 或 CNN 模型。`py -3.12 -B` 可替换为已安装 Python 3.12 的解释器路径；脚本按自身位置定位仓库根目录。

`opencv_benchmark.py` 依赖 NumPy 和 OpenCV，部署副本位于 `board/deploy/`，供板端 ARM 同帧对照使用。板端环境见[部署说明](../../../../board/deploy/README.md)，电脑识别服务与 PyQt5 依赖见[识别服务说明](../../../plate_lpr_server/README.md)。电脑端 requirements 不用于安装开发板环境。
