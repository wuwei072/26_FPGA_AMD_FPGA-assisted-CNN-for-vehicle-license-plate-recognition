# RTL 仿真步骤（Vivado 2025.1）

## 器件与仿真类型

- 板卡：PYNQ-Z2；完整芯片标识 XC7Z020-1CLG400C。
- Vivado Part：`xc7z020clg400-1`，Zynq-7000、CLG400、速度等级 -1。
- 使用 RTL Project、Vivado Simulator / XSim、Behavioral Simulation。
- 本轮只验证逻辑行为，无需 Board Part、XDC、BD、DMA IP 或综合实现；它不替代板测和实现后的时序检查。


## 1. 打开新的 Vivado 窗口

启动 Vivado 2025.1，停留在无工程打开的界面，展开底部 Tcl Console。不要在原主工程中source初始化；脚本会拒绝在已有工程的窗口中初始化。

在 **Vivado 的 Tcl Console** 输入，不能输入到 Windows PowerShell：

```tcl
source {D:/fpga_lpr/sim/run_rtl_sim.tcl}
rtl_sim_init
```

它只加入当前5个运算/分流RTL与4个testbench，排除历史测试及wrapper。新工程在 `D:/fpga_lpr/sim/work/rtl_<时间戳>/`，型号自动设为 `xc7z020clg400-1`。

## 2. 依次运行各项

每条命令会选择正确sim top、设置向量参数、启动仿真并执行 `run all`；等到 `RTL PASS`再输入下一条。不要重复点Run按钮或再额外run all。

```tcl
rtl_sim sobel single_target
rtl_sim grid single_target
rtl_sim roi single_target
rtl_sim top single_target
rtl_sim top multi_target
rtl_sim top noise_target
```

想让Sobel和网格模块各自覆盖多目标/噪声，可再执行：

```tcl
rtl_sim sobel multi_target
rtl_sim sobel noise_target
rtl_sim grid multi_target
rtl_sim grid noise_target
```

ROI独立testbench只支持single_target：前两帧预期硬编码，第三帧由内部生成并列区域/阈值定向输入。脚本会拒绝 `rtl_sim roi multi_target` 等组合，避免把向量切换误报成RTL错误。顶层三种场景已分别支持独立期望参数。

## 3. 模块、文件与期望

RTL源目录：`D:/fpga_lpr/src/fpga_edge_vision/hardware/rtl/`。
测试目录：`D:/fpga_lpr/src/fpga_edge_vision/hardware/sim/`。
向量目录：上述测试目录的 `vectors/`，使用raw BIN/HEX，不直接将PGM送入$fread。

| 命令 | simulation top | RTL |
|---|---|---|
| sobel | tb_sobel_axis | sobel_axis.sv |
| grid | tb_grid_counter | grid_counter.sv |
| roi | tb_roi_engine | roi_engine.sv |
| top | tb_sobel_grid_edge_top | sobel_axis、grid_counter、roi_engine、axis_broadcast_1to2、sobel_grid_edge_top 五个.sv |

没有独立Broadcast testbench；当前双输出顶层测试会对两路独立施加反压，验证分流及整条通路。不将旧tb_sobel_grid_top、tb_sobel_3x3_golden或旧wrapper加入当前工程。

通过标志：
- Sobel：两帧各307200像素，mismatches=0、border_nonzero=0，最后PASS。
- 网格：两帧各48个计数，mismatches=0，最后PASS。
- ROI：前两帧ROI=(160,160,160,160)、best=4、reduction=91.67%；内部第三帧期望(0,0,160,80,2,9583)。只打印前两帧，但最终PASS包含第三帧、TLAST和反压检查。
- 顶层：每帧edge_pixels=307200、edge_mismatches=0、roi_mismatches=0，最后PASS；两帧合计614400个边缘像素。

| 顶层场景 | x,y,width,height,best_grids,reduction_x100 |
|---|---|
| single_target | 160,160,160,160,4,9167 |
| multi_target | 80,80,240,160,6,8750 |
| noise_target | 400,160,160,160,4,9167 |

当前总线双输出testbench是`#10`、50MHz；三个单模块testbench是`#5`、100MHz。这里100MHz是功能仿真激励，不代表实现后的电路满足100MHz时序。

## 4. 日志与波形

每次仿真保存到：

```text
D:/fpga_lpr/sim/logs/rtl_<本轮时间戳>/<模块>_<场景>_<时间戳>/
  case_info.txt
  compile.log
  elaborate.log
  simulate.log
```

本轮日志父目录另有source_files.txt，记录工具版本、源文件路径、大小与修改时间。它用于定位版本，不能替代最终产物哈希清单。

通过后仿真窗口保留，可截图波形。下一条 `rtl_sim` 会关闭上一轮仿真再启动新轮，日志已分目录保存。波形可关注testbench的aclk、aresetn、输入/输出valid/ready/data/last；顶层同时关注ROI与edge两路输出。若要保留自定义wave配置，在切换前自行保存。

如果看到ERROR、FAIL、编译/展开错误或“No clean PASS”，先看对应case目录日志，不继续把该case记为通过。默认1000ns通常不足以完成整帧，判断以PASS和$finish为准。编译成功、launch_simulation返回都不是功能通过证明。

## 5. 不用辅助函数时，原生Tcl怎样设置

辅助工程已建立后，以Sobel为例：

```tcl
catch {close_sim}
set vec {D:/fpga_lpr/src/fpga_edge_vision/hardware/sim/vectors}
set_property top tb_sobel_axis [get_filesets sim_1]
set_property -name xsim.simulate.xsim.more_options \
    -value "-onfinish stop -testplusarg IN=$vec/single_target_640x480_input.bin -testplusarg EXP=$vec/single_target_640x480_expected.bin" \
    -objects [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation -simset sim_1 -mode behavioral
run all
```

原生操作的日志不会由辅助函数自动归档；切换下一项前自己保存，或直接用第2节命令。值以`-`开头时使用上面的`-name/-value/-objects`形式，避免Vivado误把整串参数解析为set_property选项。

参数区别：Sobel用IN/EXP；网格用EDGE/COUNTS；ROI只用COUNTS；双输出顶层用IN/EDGE/EXPECTED。每次重设more_options应覆盖整串，而不是叠加上一项参数。

## 验证范围

辅助脚本已经在本机Vivado 2025.1完成ROI工程创建、参数设置、编译和展开；批处理环境在XSim内核启动阶段未完成，已停止该临时进程。尚未取得本轮功能PASS，不能把这次工具流程核对写成RTL通过。请按本文在新Vivado图形窗口执行，并保存真实结果。

## 官方资料

- [TUL PYNQ-Z2器件说明](https://www.tul.com.tw/images/PYNQ-Z2_PA_v2_pp_20201209_STD.pdf)
- [AMD UG835：launch_simulation](https://docs.amd.com/r/2025.1-English/ug835-vivado-tcl-commands/launch_simulation)
- [AMD UG900：仿真属性](https://docs.amd.com/r/2025.1-English/ug900-vivado-logic-simulation/Vivado-Simulator-Simulation-Options)
- [AMD UG900：xsim参数](https://docs.amd.com/r/2025.1-English/ug900-vivado-logic-simulation/xsim-Executable-Options)
