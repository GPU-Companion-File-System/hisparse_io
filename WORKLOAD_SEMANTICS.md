# IO 参数与 HiSparse 对照

当前结果是合成的离散 NVMe→HBM 微基准。`request_batch`、`top_k` 和 `miss_rate` 只用于把一个假设的一层 decode miss 负载换算成 IO 数量；后端实际接收的是随机 4 KiB 读列表。

| 字段 | 本项目含义 | 边界 |
|---|---|---|
| `request_batch` | 模拟的一层 decode 调用包含的本地请求数 | 不是整个服务的并发数，也不是 SSD 队列深度 |
| `top_k` | 每请求、每层、每个 decode step 选中的 KV 条目数，固定为 2048 | 不是上下文长度，也不是缺失数 |
| `miss_rate` | 假定选中条目中不在 GPU 热缓存的比例 | 不是本次硬件运行测得的 miss rate |
| `n_reads` | `round(batch × top_k × miss_rate)` 个 4 KiB SSD 读 | 不是完整模型一步或整个生成过程的 IO 总数 |
| `queue_depth` | 逻辑在途 IO 上限，256 | 不是每轮的 IO 数 |
| `submission_group` | 每次提交最多 16 个 IO | 不是 16 个模型请求 |

这里没有真实 TopK、LRU、逐层推理、请求合并、主机缓存命中或跨层局部性。

参考配置来自 HiSparse 的 locality 结果：4096 个 GPU 缓存槽位时平均 miss rate 13.4%，8192 个槽位时 6.7%，只保留当前 TopK 条目的 staging 基线为 30%。本项目选择 local batch `1 / 4 / 16 / 64` 作为代表尺度。它们是论文参数的合成映射，不是原始 SSD trace。

```text
n_reads = round(local_decode_batch × 2048 × reference_mean_miss_rate)
```

主场景 13.4% 对应 `274 / 1098 / 4391 / 17564` 次读取。取整发生在每个整批配置上；4100、41000 之类的整数来自另一种“先按每请求取整再乘 batch”的旧写法，本仓库不再使用那组配置。

原始 HiSparse 的缺失补入路径是主机 pinned memory → GPU HBM。本项目把一个逻辑 miss 映射成一个 4 KiB SSD 读，只用于比较两个数据通路的微基准性能。真实系统还需要根据模型、dtype、分片和物理布局决定 KV 记录大小、读合并和主机缓存策略。

参数详情见 [`results/hisparse-derived-workload-profile.json`](results/hisparse-derived-workload-profile.json) 和 [`results/hisparse-paper-parameters.md`](results/hisparse-paper-parameters.md)。
