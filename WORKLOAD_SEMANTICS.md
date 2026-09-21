# 当前 IO 参数含义与 HiSparse 对照

当前结果是合成的离散 NVMe→HBM 微基准。`request_batch`、`top_k`、`miss_rate` 是把假设的一层 decode miss 负载换算成 IO 数量的输入；没有执行模型、TopK、LRU 或真实请求调度。

| 字段 | 当前含义 | 不能直接解释成 |
|---|---|---|
| `request_batch` | 这次模拟的一层 decode 调用包含多少个本地请求 | 整个多 GPU 服务的并发数；SSD 队列深度 |
| `top_k` | 每请求、每层、每个 decode step 选出的 KV 条目数，当前固定 2048 | 上下文长度；缺失数 |
| `miss_rate` | 假设选中条目中不在 GPU 热缓存的比例；当前是人为输入 | 实测 miss rate；选中条目占全部上下文的比例 |
| `n_reads` | 该轮实际提交的 4 KiB SSD 读请求总数 | 完整模型一步/整个生成过程的总 IO |
| `round` | 固定配置下的一次计时重复 | 已运行的真实模型 token step |
| `queue_depth=256` | 逻辑未完成 IO 上限 | 每轮总 IO 数 |
| `submission_group=16` | 一个提交窗口最多处理的 IO 数 | 16 个模型请求 |

在当前后端中，`request_batch` 和 `miss_rate` 只影响生成时的 `n_reads`，之后作为标签保存。后端看到的是扁平的随机 IO 列表；没有请求分组、缓存局部性或跨层时序。两个不同的 batch/rate 组合若给出相同 `n_reads`，就具有相同 IO 数量和策略，差异来自随机地址、运行顺序与系统状态，不能解释成真实模型 batch 效应。

## 4100 和 41000 的来源

初版执行方案（仅在本地归档，不随仓库发布）指定，且 `src/prepare_workload.py` 实现：

```text
n_reads = request_batch × round(2048 × miss_rate)
20% miss → round(409.6) = 410 次/请求
10 个请求 → 4100 次
100 个请求 → 41000 次
```

这是“每请求固定整数缺失数”的合成假设。若换成“整批期望缺失数取整”，则 `round(10×2048×0.20)=4096`，`round(100×2048×0.20)=40960`。两者只是不同取整粒度；当前代码遵循了原公式，并非算术错误。真实缺失数本来就不需要是 2 的幂。

一轮 41000 次读取仍通过 256 的在途上限滚动完成；报告 p50 是整轮 IO 完成延迟，不是完整模型的生成 token 延迟。

## 可采用的 HiSparse 依据

论文的 GLM-5.1 LongBenchV2 locality 实验，`top_k=2048`：每请求每层 4096 槽的 LRU 平均 miss 为 13.4%，8192 槽的 LRU 为 6.7%；只保留 2048 个当前 TopK 条目的 staging 基线为 30%。这些是该 trace 的均值，不能推广为任意模型/层/步的固定实测率。[论文 §4.3](https://arxiv.org/html/2608.07009v1#S4.SS3)

参考配置见 [hisparse-derived-workload-profile.json](results/hisparse-derived-workload-profile.json)，现已完成四阶段重跑，见 [最新报告](results/run-20260907-101847-hisparse/REPORT.md)。历史结果保留：

- 以 `top_k=2048`、4096 槽 LRU、参考均值 13.4% 为主场景；6.7% 和 staging 的 30% 作对照。
- 本地 batch 取 1、4、16、64，作为论文 kernel batch 图中的代表尺度；不是宣称这些就是全部原始采样点。[论文 §4.4 / Fig.7](https://arxiv.org/html/2608.07009v1#S4.SS4)
- 此 JSON 用 `round(local_decode_batch×top_k×reference_mean_miss_rate)` 生成整批均值近似。主场景对应 274、1098、4391、17564 次逻辑缺失。
- 若取得逐层逐步 trace，应改用各请求实际缺失数之和，再执行明确的物理块映射；不继续用一个平均率替代缺失分布。

论文用符号 B 表示缓存槽位数，而非 batch，容易混淆。此项目后续宜用 `local_decode_batch`、`gpu_cache_slots_per_request_per_layer`、`target_miss_rate`、`effective_miss_rate` 分别标识。

## 逻辑 miss 与物理读的边界

HiSparse 的实际层级是 CPU pinned memory→GPU HBM，完整 KV 数据保留在主机内存。其 `device_buffer_size` 单位是每请求的 token 槽位；`swap_in_block_size` 是 CUDA 线程块大小，不是磁盘 IO 大小。[官方指南](https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/hisparse_guide.mdx)

我们的“一条 miss 对应一次 4 KiB SSD 读”是扩展到 NVMe 的布局假设。KV 记录字节数应按模型、dtype 和分片确定；实际 SSD IO 数还取决于对齐、多个记录共享一块、合并读，以及主机缓存能否命中。因此不能把 HBM miss rate 直接称为 SSD miss rate。若加了主机缓存，应统计真正继续落到 SSD 的缺失，再转换为物理 IO。

仅扫描均值与总读数可以回答特定合成 IO 下两个后端的延迟差异；HiSparse 相关性还需要真实访问局部性、每层每步缺失变化和具体 KV 存储布局。

更多来源和论文/早期博客的模型差异见 [参数依据](results/hisparse-paper-parameters.md)。
