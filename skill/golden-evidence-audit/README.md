# 黄金比对与结果取证

## 适用场景

用于固定形状的图像、音频或数值加速器裸二进制比对，以及同版本工程报告、产物和性能数据的整理。Python 3.8+ 标准库即可运行；报告解析支持 Vivado 常见文本格式。

## 使用方法

在本技能目录执行。示例生成合成输入、报告和计时数据：

```text
python scripts/selftest.py
python examples/create_demo.py demo_output
python scripts/compare_binary.py demo_output/magnitude.bin demo_output/captured.bin --dtype u8 --shape 2,3 --threshold 80 --json demo_output/comparison.json
python scripts/collect_evidence.py demo_output/manifest.json --output demo_output/report
```

比较应为 PASS；去掉 `--threshold 80` 则应为 FAIL。演示输出保存在 `demo_output/`，不作为硬件测量结果。

### 换成自己的输出

先确定形状、类型、端序、排列、输出语义、边界、舍入/饱和和允许误差。支持 u8/i8/u16/i16/u32/i32/f32/f64、小端或大端、行优先维度，脚本不会从文件内容猜测契约。例如比较 1024 个 16 位有符号采样：

```text
python scripts/compare_binary.py golden.bin measured.bin --dtype i16 --shape 1024 --byteorder little --json comparison.json
```

- 元数据与完整输出分别比较；少量坐标字段一致不能替代逐像素或逐采样点核验。保留失败数和首批差异坐标，不为得到 PASS 修改黄金文件。
- 只有契约规定“参考幅值转二值”时才用 `--threshold`：仅转换参考，规则为 `参考 >= threshold ? on_value : 0`，默认 `on_value=255`，可用 `--on-value` 指定。规则为 `>` 时应在参考导出器中实现，不能近似挪动阈值。
- 浮点容差通过 `--atol` / `--rtol` 设置，按 `math.isclose` 比较，容差须有算法依据。NaN 不视为相等，含 NaN/无穷大的参考不能做阈值转换。退出码：0=PASS，1=数值不同，2=输入或配置错误。

### 换成自己的工程材料

复制生成的 `demo_output/manifest.json` 为自己的清单，修改以下内容；文件路径相对清单所在目录：

- `build_id` 写版本，`variant` 写时钟和数据通路；`artifacts` 的 `role/path` 改成自己的源码、bitstream、交付文件等。
- `timing`、`utilization` 指向同一实现的时序和资源报告；不用 Vivado 可省去。`latencies` 指向自己的计时 CSV，没有实测就省去，不填写示例数字。
- 有构建时已保存的可信 SHA256，才在 artifact 的 `sha256` 中填入用于核验的摘要。未提供时只记录当前哈希，标为 NOT_PINNED；不能把刚计算的当前哈希当作独立构建证据。

计时 CSV 首行保持：

```text
sample_id,input_sha256,method,boundary,elapsed_ms
```

`sample_id` 每次重复测量使用新编号，两种方法共享同一次编号；`input_sha256` 是冻结输入字节的真实哈希；`method` 如 cpu/fpga；`boundary` 写实际起止边界；`elapsed_ms` 为实测正数。编号、方法和边界不能为空，同方法/样本重复行会被拒绝。

在清单的 `compare_methods` 中指定两个方法，顺序为耗时比的分子、分母。只有样本编号、输入摘要和边界都相同才配对。测量者另行记录预热策略、采样次数，以及采集、读盘、编码、网络是否计入；工具不会自行剔除预热或离群值。

编辑完成后运行：

```text
python scripts/collect_evidence.py manifest.json --output report
```

输出为 `report/evidence.md` 和 `report/evidence.json`，包含解析值、来源哈希、配对记录和待核实项。缺少的指标保持 UNKNOWN，不补成 0；生成报告不代表硬件通过。

## 来源与验证

方法源于两类实际问题：Golden 保存 Sobel 幅值、硬件返回阈值二值图，造成 ROI 字段一致但像素比较失败；不同时钟和数据通路的实现报告，以及历史 CPU 耗时和当前 FPGA 耗时被混用。因此先核实输出语义，再按版本、输入和计时边界组织证据。

10 项标准库自测已通过，覆盖语义转换、长度/端序、NaN 与容差、报告 PASS/FAIL/UNKNOWN、文件身份提示、同输入配对和无效样本拒绝。报告解析已用 Vivado 2025.1 Routed 文本核对，验证范围为离线比对和报告解析。

## 失效条件

- 压缩、变长、位打包或带包头/行填充的数据，先按接口导出规范裸数据；浮点非确定性应先定义误差和统计指标。
- 其他厂商、未知 Vivado 格式或非 Routed 报告需检查 UNKNOWN 并核对解析器。报告内 PASS 只覆盖脚本识别的检查，不能替代完整约束、CDC/复位和板端验证。
- 报告日期或 Device 文字不同只提示核实，不能直接判定不同构建或芯片；应检查完整器件、时钟、源码和工具配置。
- 哈希匹配只证明文件身份，不能证明源码、报告、bitstream 同一次生成，更不能证明拿这些文件测过硬件。功能、输入或计时边界不可比时不算统一加速比；没有实测就不推导功耗、识别率或 CNN 收益。
