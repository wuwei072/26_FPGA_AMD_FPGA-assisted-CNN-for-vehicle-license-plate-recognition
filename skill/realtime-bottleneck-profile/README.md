# 实时系统瓶颈定位

## 适用场景

适合硬件或模型调用很快、整机显示却卡顿的连续采样程序。分段计时和日志分析只需 Python 3.8+ 标准库；图片编码实验另需 NumPy、OpenCV。

## 使用方法

在本技能目录运行自测和合成示例：

```bash
python scripts/selftest.py
python scripts/demo_trace.py --output trace.jsonl
python scripts/analyze_trace.py trace.jsonl --output profile.md
```

合成示例用于检查日志和报告格式。分析实际程序时，将最后一条命令的 `trace.jsonl` 换成实测日志路径。

将 `scripts/frame_probe.py` 放到程序可导入的位置，用自己的业务调用替换下面四个函数：

```python
import json
from frame_probe import FrameProbe

with open("run.jsonl", "w", encoding="utf-8") as log:
    for frame_id in range(100):
        probe = FrameProbe(frame_id, mode="demo")
        with probe.stage("capture"):
            frame = read_one_sample()
        with probe.stage("accelerator_call"):
            result = process_sample(frame)
        with probe.stage("encode"):
            payload = encode_result(frame, result)
        with probe.stage("ui_submit"):
            submit_to_ui(payload)
        log.write(json.dumps(probe.finish()) + "\n")
```

接入时保留以下约定：

- 用 `mode` 分开记录演示、基准等工作负载。阶段可以嵌套或并行，分析器按区间并集计算覆盖时间，不能把各行耗时直接相加。
- `add_span` 只接收同一主机、同一单调时钟的区间。跨主机的 `perf_counter` 数值不能直接比较。
- 本轮所有 `stage` 退出后再调用 `finish()`，结束后不能追加区间；手动记录异步区间时，调用方必须先收齐。长 HTTP 请求单独记录事务，不要为计时阻塞主循环。
- `loop` 是本轮主机墙钟时间；UI 提交不等于真正显示，日志写盘也不在本轮计时内。异常阶段不计入阶段均值，其所在帧不计入完整循环均值。
- 计时、写盘和界面指标会扰动程序，短期采样后关闭。图像、结果和耗时按 `frame_id` 配对，显示队列及异步请求数量保持有界。

根据报告先找主要耗时，再一次只改一项，例如关闭逐帧参考计算、减少转换或更换编码。前后保持输入、算法、尺寸和计时边界一致，先核验输出等价，再比较总循环；线程无改善就回退。实验提示词见 [workflow.md](references/workflow.md)。

## 可选：图片编码实验

在已有 NumPy、OpenCV 环境中运行：

```bash
python scripts/codec_probe.py --color color.png --binary binary.png --repeat 20
```

`binary.png` 必须是原生单通道 uint8、仅含 0/255。探针比较普通与 1-bit PNG，打印编码均值、P95、大小、实际位深和解码逐像素一致性；失败时保留原编码。JPEG 用于有损显示。读盘、二值检查和解码核验不计入编码时间。

## 来源与验证

方法源于实时视频链路的性能排查：硬件调用较快时，逐帧 CPU 对照、PNG 编码和界面提交仍可能占据主要时间；关闭参考计算后也需要重新测量。采集线程未显著改善循环、退出时读取未返回的案例，说明并发改动还需检查设备所有权和退出行为。因此采用分段计时、单变量实验及输出等价性核验。

6 项标准库自测已通过，覆盖区间并集、模式隔离、异常帧、无效时间及未结束/迟到区间。编码探针在 OpenCV 4.10.0、NumPy 环境中以合成图验证了普通 PNG 与 1-bit PNG 的位深和解码一致性，并确认包含中间灰度值的二值输入被拒绝。

验证范围为离线工具逻辑和编码兼容性，实际设备性能及跨项目适用性需在目标环境验证。

## 失效条件

未记录的相机缓冲、跨机传输和屏幕呈现延迟无法由报告推断；阶段耗时的倒数不能作为实际显示 FPS。输入、参考计算开关或计时边界改变时，前后数据不能直接说明优化收益。异步区间不完整、时钟不一致时不能归因；非二值图或不支持 1-bit PNG 的 OpenCV 构建不适用该编码方案。
