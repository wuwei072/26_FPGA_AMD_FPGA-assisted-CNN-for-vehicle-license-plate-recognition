---
name: dma-transaction-debug
description: 为流式硬件加速器建立可复用 DMA 事务，处理缓存同步、收发顺序、超时与长度错误；提供 PYNQ Simple AXI DMA 适配器及故障定位步骤。
---

# DMA 事务与故障定位

先读 [README.md](README.md) 确认适用范围。接口尺寸、通道个数、输出含义由用户工程决定，不能套用图像项目的常量。

1. 收集输入/输出字节数、dtype、端序、TLAST 定义、通道方向、Simple/SG 模式、驱动版本与缓存策略。区分输出最大容量和预期实际长度。
2. 每块缓冲分配一次；一个执行者独占这些通道。完成前不得重填输入、读取输出或释放物理内存。
3. 所有接收先启动，最后启动发送。轮询同时检查状态错误和期限；无中断连线时不使用依赖中断的等待方式。
4. 传输完成后执行驱动的接收缓存同步，再核验长度、复制需要跨帧保存的结果。`idle` 不等于 CPU 已看到最新数据。
5. 部分启动、超时、异常中断后停止后续事务并保留缓冲引用；记录寄存器。按实际平台恢复 DMA/上游协议状态，不能把下一帧直接重试当恢复。

PYNQ Simple AXI DMA 可从 [scripts/dma_transaction.py](scripts/dma_transaction.py) 使用 `Endpoint`、`axi_dma_endpoint`、`PollingTransaction`。固定长度以外的输出、SG、VDMA 或别的驱动须先改适配器及完成判据，不能机械复制偏移。

故障按 [references/diagnosis.md](references/diagnosis.md) 分层定位。核对安装版本的 `transfer()` 与 `wait()`，确认缓存语义后再用模板。计时中明确 DMA 窗口、完整调用与端到端显示的边界。

验证先运行 `python scripts/selftest.py`；再在目标设备执行最小确定性样本、短包/错误协议测试（如果测试环境允许）、连续多轮复用。报告中必须区分模拟驱动测试和实际硬件验证。
