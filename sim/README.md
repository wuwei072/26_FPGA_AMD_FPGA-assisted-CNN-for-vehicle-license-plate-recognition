# RTL 仿真

使用Vivado 2025.1 / XSim行为仿真，目标器件为PYNQ-Z2的 `xc7z020clg400-1`。这里验证RTL逻辑，无需Board Part、BD、DMA IP、XDC或综合实现；结果不替代上板测试和布局布线后时序检查。

## 唯一文件位置

- 运算与分流RTL：`src/fpga_edge_vision/rtl/`。helper只加入5个SystemVerilog文件，BD wrapper留给硬件构建使用。
- 4个testbench：`sim/rtl/`。
- 输入向量：`data/hdl_vectors/`，格式和参考语义见[数据说明](../data/README.md)。
- 可重建的XSim工程与波形：`sim/work/`，不上传。
- 仿真结果：`sim/logs/`，保留六组运行结果、对应参数和源码列表，共13文件。

## 运行六组测试

启动新的Vivado窗口，保持无工程打开。在Vivado的Tcl Console中执行以下命令，`repo_root`替换为当前仓库的实际根目录：

```tcl
set repo_root [file normalize {D:/26_FPGA_AMD_FPGA-assisted-CNN-for-vehicle-license-plate-recognition-main}]
source [file join $repo_root sim run_rtl_sim.tcl]
rtl_sim_init $repo_root
```

helper创建独立工程，不关闭或改写其他工程。当前XSim参数拼接要求仓库路径不含空格，检测到空格会明确报错；建议使用短英文路径，例如 `D:/fpga_lpr`。

依次输入，等每组出现 `RTL PASS`再运行下一组：

```tcl
rtl_sim sobel single_target
rtl_sim grid single_target
rtl_sim roi single_target
rtl_sim top single_target
rtl_sim top multi_target
rtl_sim top noise_target
```

每次调用会设置正确top和绝对向量路径，启动仿真并执行 `run all`，然后保存独立日志。无需额外点击Run按钮。编译成功或只运行默认1000ns都不能视为通过。

| 调用 | 仿真顶层 | 输入参数 |
|---|---|---|
| `sobel` | `tb_sobel_axis` | `IN`：灰度BIN；`EXP`：Sobel幅值BIN |
| `grid` | `tb_grid_counter` | `EDGE`：Sobel幅值BIN；`COUNTS`：48项HEX计数 |
| `roi` | `tb_roi_engine` | `COUNTS`：single_target的48项HEX计数 |
| `top` | `tb_sobel_grid_edge_top` | `IN`、`EDGE`、`EXPECTED`六字段 |

ROI前两帧期望固定为single_target，第三帧在TB内生成平局与阈值边界用例；只打印前两帧，最终 `PASS`条件包含三帧、TLAST和反压检查。不能直接把ROI测试换成multi/noise的计数文件；helper会拒绝这种调用。

Sobel和网格模块还可使用multi_target/noise_target；顶层三组期望如下：

| 向量 | `x,y,width,height,best_grids,reduction_x100` |
|---|---|
| single_target | `160,160,160,160,4,9167` |
| multi_target | `80,80,240,160,6,8750` |
| noise_target | `400,160,160,160,4,9167` |

## 检查范围与时钟

Sobel每帧比较307200个像素并检查零边界；网格每帧比较48个计数；顶层同时检查每帧边缘像素与6个ROI字段，且对两路输出独立施加反压。正常测试均需明确的 `PASS`和 `$finish`，不能有 `FAIL`、`ERROR`、像素/字段、TLAST或反压检查错误。

模块TB为100MHz（`#5`），双输出顶层TB为50MHz（`#10`）；这些是功能仿真，不代表模块已通过100MHz实现时序验收。

## 六组仿真结果

运行日志包含逐帧比较汇总，完整比较条件定义在对应testbench中。每组结果包含 `simulate.log` 与 `case_info.txt`，运行源文件列表见 [source_files.txt](logs/rtl_20261030_210106_1793365266495/source_files.txt)。

| 测试 | 运行结果 | 参数 | 日志记录 |
|---|---|---|---|
| Sobel / 单目标 | [simulate.log](logs/rtl_20261030_210106_1793365266495/sobel_single_target_1793365312158/simulate.log) | [case_info.txt](logs/rtl_20261030_210106_1793365266495/sobel_single_target_1793365312158/case_info.txt) | 两帧各307200像素；像素误差0、边界非零0，PASS |
| Grid / 单目标 | [simulate.log](logs/rtl_20261030_210106_1793365266495/grid_single_target_1793365339045/simulate.log) | [case_info.txt](logs/rtl_20261030_210106_1793365266495/grid_single_target_1793365339045/case_info.txt) | 两帧各48项计数；误差0，PASS |
| ROI / 单目标 | [simulate.log](logs/rtl_20261030_210106_1793365266495/roi_single_target_1793365352706/simulate.log) | [case_info.txt](logs/rtl_20261030_210106_1793365266495/roi_single_target_1793365352706/case_info.txt) | 打印的两帧ROI均为(160,160,160,160)、4格；误差0，PASS |
| Top / 单目标 | [simulate.log](logs/rtl_20261030_210106_1793365266495/top_single_target_1793365375341/simulate.log) | [case_info.txt](logs/rtl_20261030_210106_1793365266495/top_single_target_1793365375341/case_info.txt) | 两帧边缘及ROI字段误差0，PASS |
| Top / 多目标 | [simulate.log](logs/rtl_20261030_210106_1793365266495/top_multi_target_1793365393826/simulate.log) | [case_info.txt](logs/rtl_20261030_210106_1793365266495/top_multi_target_1793365393826/case_info.txt) | ROI=(80,80,240,160)、6格；边缘及ROI字段误差0，PASS |
| Top / 噪声目标 | [simulate.log](logs/rtl_20261030_210106_1793365266495/top_noise_target_1793365407848/simulate.log) | [case_info.txt](logs/rtl_20261030_210106_1793365266495/top_noise_target_1793365407848/case_info.txt) | ROI=(400,160,160,160)、4格；边缘及ROI字段误差0，PASS |

日志中的绝对路径表示运行时位置。复现使用本说明上方的Tcl入口和根目录data向量。
