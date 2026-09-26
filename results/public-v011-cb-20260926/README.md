# 历史 GDS 与公开 Tutti v0.1.1 关键对照

这组结果把 2026-09-07 已成功完成的历史 GDS A1+A2 样本，与 2026-09-26 在同一块物理 SSD 上重新测得的公开 Tutti v0.1.1 样本放在一起。两边使用同一个 16 GiB 数据文件、同一个确定性 trace、同一组 12 个配置；设备身份和输入哈希见 [`verification.json`](verification.json) 与 [`input-sha256.txt`](input-sha256.txt)。

物理盘为 PCI `0000:cb:00.0`、序列号 `PHCP418201G07P6CGN`。公开 Tutti 使用上游 commit `38c8a68ab99c47a9a31f120b1018b6a7e01734d1`（v0.1.1），设备节点为 `/dev/snvme0n1` / `/dev/ssnvme0`。公开 Tutti 原始 CSV 共 2,544 行，其中每个配置 200 个 `phase=1` 正式样本；所有行均通过 GPU 数据校验，提交数和 kernel launch 数均为 1,156,884。

## 表格

- [`KEY_COMPARISON.md`](KEY_COMPARISON.md)：适合阅读的 12 配置 p50/p99 表，延迟单位为 ms。
- [`comparison.csv`](comparison.csv)：同一表的原始微秒数值和加速比。
- [`raw-B.csv`](raw-B.csv)：公开 Tutti 的完整原始记录。

表中加速比定义为 `GDS / public Tutti`；大于 1 表示公开 Tutti 延迟更低。GDS 数值来自历史归档的 A1+A2 合并统计，公开 Tutti 数值由本目录原始 CSV 的 200 个 `phase=1` 样本按 NumPy 线性百分位重算。

这是一组严格的输入和物理设备对照，不是同一时刻的同步 A/B 运行：GDS 样本来自 2026-09-07，当前主机随后出现 NVIDIA DMA mapping 故障，无法重新采集 GDS。因此结果可以作为当前唯一关键对照归档，但不能声称消除了日期、驱动状态和阶段漂移等时间因素。

本目录不包含实际数据文件和 `trace.bin`。数据文件和 trace 仍保留在实验机上，哈希已记录；代码仓库只提交可复核的统计结果和原始 Tutti CSV。
