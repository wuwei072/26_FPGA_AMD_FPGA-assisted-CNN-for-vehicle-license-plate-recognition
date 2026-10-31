# DMA 事务与故障定位

## 适用范围

用于一路输入、一路或多路输出的流式加速器，如滤波、FFT、压缩。随包代码适配 **PYNQ 的 AMD AXI DMA、Simple 模式、固定长度输出**，需要已有的 PYNQ/NumPy 环境。其他驱动可复用事务顺序，但须修改寄存器与缓存适配。

## 使用方法

将 [scripts/dma_transaction.py](scripts/dma_transaction.py) 放到设备程序旁。先明确每路 dtype、端序、字节数、TLAST、驱动版本和缓存策略。下面以 **1024 个 uint16 原样回传的测试核**为例；须自备配对的 `identity.bit/.hwh`，替换成自己的 IP 名称、长度和数据格式。加载 Overlay 会更换当前硬件设计。以下是交互式会话或宿主程序中的接入片段；若写成独立脚本，须捕获 `run()` 异常，并在硬件恢复前保持进程和缓冲，不能让未处理的异常直接退出。

```python
import numpy as np
from pynq import Overlay, allocate
from dma_transaction import axi_dma_endpoint, PollingTransaction

overlay = Overlay("identity.bit")
dma = overlay.axi_dma_0
input_buf = allocate(shape=(1024,), dtype=np.uint16)
output_buf = allocate(shape=(1024,), dtype=np.uint16)
tx = PollingTransaction(
    axi_dma_endpoint(dma, "send", input_buf, "input"),
    [axi_dma_endpoint(dma, "recv", output_buf, "result")],
    timeout_s=3.0,
)
input_buf[:] = np.arange(1024, dtype=np.uint16)
outputs, dma_ms = tx.run()
result = np.frombuffer(outputs["result"], dtype="<u2")
assert np.array_equal(result, np.arange(1024, dtype=np.uint16))

# 连续调用复用这些缓冲，最后一次确认结束后再释放。
if tx.safe_to_release:
    input_buf.freebuffer()
    output_buf.freebuffer()
```

多路输出时，在接收列表增加绑定其他 S2MM 通道的端点；各缓冲格式和大小可不同，内存不得重叠。`run()` 先启动所有接收，最后发送，轮询错误和期限；完成后核验每路长度等于缓冲容量，返回独立的 `bytes` 快照。

使用时保留以下约束：

- 通道由一个执行者独占。锁只保护事务入口，调用期间主程序不能改写输入；首次接管时 `idle=False` 不一定表示有旧事务，仍需确认没有其他使用者。
- 全部通道 `idle` 后仍调用驱动 `wait()` 完成缓存同步和记账。PYNQ Simple DMA 的 `send.transfer()` 刷新发送缓存、`recv.wait()` 失效接收缓存；迁移或升级前核对安装版本的实现。
- `safe_to_release=False` 时保留进程和缓冲，记录状态，按平台流程停止/复位 DMA 与上游，必要时重新上电；不得释放、退出自动释放上下文或另起程序接管。强引用只防当前进程内误回收，不能阻止手动释放或保证退出进程后安全。
- 故障后封装禁止重用，不自动恢复硬件。`dma_ms` 从准备启动到所有 `wait()` 返回，含缓存操作，不含输入填充、长度核验和输出复制；完整调用应另行计时。

故障现象、状态读取和排查顺序见 [references/diagnosis.md](references/diagnosis.md)。

## 问题来源与验证

事务流程提炼自双输出加速器的接口审查和 DMA 联调：

- 多输出分支可能通过背压相互阻塞，因此先启动全部接收，再发送输入。
- 原驱动在所有通道 idle 后调用 wait 并复制输出，用于完成缓存同步和保存跨轮结果。
- 无中断等待及超时处理需要有期限轮询；完成状态不明时保留缓冲并停止重用。

无硬件自检（Python 3.8+ 标准库）：

```bash
python scripts/selftest.py
```

**7/7 项自测通过**，覆盖接收顺序、缓存回调、独立副本、复用、超时、DMA 错误、部分启动、短包、重入和外部占用。测试使用模拟通道，封装尚未完成实机验证；迁移后须用确定性小样本和连续传输验证真实 DMA 与缓存行为。

## 失效条件

- SG、VDMA、CDMA 或非 AMD DMA：需要重做寄存器及完成适配。
- 变长包、按行 TLAST、长度超限、无 DRE 时地址或长度不对齐：先改契约、拆分或调整缓冲，不能只增大超时。
- 驱动缺少缓存同步，或 idle 后的 `wait()` 仍等待中断：当前适配器不适用。
- 多调用者共享通道或缓冲重叠：独占所有权前提不成立。

实现参考：[PYNQ DMA 驱动](https://github.com/Xilinx/PYNQ/blob/master/pynq/lib/dma.py)的 `transfer()/wait()`、[Buffer API](https://pynq.readthedocs.io/en/latest/pynq_package/pynq.buffer.html)。链接版本会变化，使用时以设备安装版本为准。
