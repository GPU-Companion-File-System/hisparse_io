# 公开 Tutti v0.1.1 状态

公开 v0.1.1 的用户态 benchmark 已完成完整矩阵运行，2,544 条记录全部通过 GPU 数据校验。关键结果归档在 [`results/key-comparison-cb-20260926/`](../results/key-comparison-cb-20260926/)。

- 上游 commit：`38c8a68ab99c47a9a31f120b1018b6a7e01734d1`
- 物理盘：PCI BDF `0000:cb:00.0`
- 公开 Tutti 设备：`/dev/snvme0n1` / `/dev/ssnvme0`
- 每个配置：200 个正式样本；GDS 保留 A1/A2 两个成功阶段，Tutti 保留一个完整矩阵

结果目录提供原始 CSV、cuFile 配置、日志、输入哈希、workload/profile 元数据和统一统计表。公开 Tutti 的结果使用公开 API；旧部署适配器和旧 Tutti 结果已从仓库移除。

当前仓库不提交内核模块、daemon、第三方源码、动态库、数据或 trace。重新运行前必须确认公开用户态版本与 snvme 内核 ABI、daemon 配置、BDF 和 backing device 一致，并按 [`docs/RUNNING.md`](RUNNING.md) 做只读预检。
