# HiSparse parameter evidence

Checked 2026-09-07. Primary sources only. No GPU workload was run.

## Paper: experimentally configured versus measured

[HiSparse, arXiv:2608.07009v1](https://arxiv.org/html/2608.07009v1), August 2026:

| Evidence | Value | Status / locator |
|---|---|---|
| DSA selection | 2048 records/query/layer | Configured; §4.1 |
| Cache capacity | Per-request, per-layer record slots | Definition; Table 2 |
| Kernel batch | 16 for cache-capacity sweep | Configured; Fig. 7 |
| Kernel batch axis | 1, 4, 16, 64 | Axis labels; Fig. 7, PDF p.13 |
| Cache ratio | 1, 2, 4, 8 times selection size | Sweep; Fig. 7 |
| End-to-end concurrency | 8, 16, 32, 64, 128, 256 | System-wide; 8 H200s; §4.6/Fig. 8 |
| Context | 32K input, 8K output | Configured; §4.1 |
| Cache locality trace | GLM-5.1, LongBenchV2, 100384-token prompt, 78 layers | Trace; §4.3 |
| Averaging window | First 1000 decode steps | Fig. 6/§4.3 |
| Staging, 2048 slots | 30% misses | Measured mean; §4.3 |
| LRU, 4096 slots | 13.4% misses | Measured mean; §4.3 |
| LRU, 8192 slots | 6.7% misses | Measured mean; §4.3 |
| Storage | Pinned host DRAM ↔ GPU HBM | Implemented; §3.2 |
| NVMe | Higher-latency capacity extension | Discussion, not evaluated; §5 |

The miss denominator is selected records, not full context. These rates describe one trace, not universal constants. Cache capacity is denoted **B** in the paper; batch is **N_batch**. Fig. 7 measures one kernel invocation; Fig. 8 measures a complete serving system.

Direct locators: [locality §4.3](https://arxiv.org/html/2608.07009v1#S4.SS3), [kernel study §4.4](https://arxiv.org/html/2608.07009v1#S4.SS4), [end-to-end prefetch §4.6](https://arxiv.org/html/2608.07009v1#S4.SS6), [PDF p.13, Fig.7](https://arxiv.org/pdf/2608.07009v1#page=13).

## Earlier first-party blog: different trace/model

The [authors' April 2026 LMSYS article](https://www.lmsys.org/blog/2026-04-10-sglang-hisparse/) labels its locality graph **DeepSeek-V3.2**, LongBenchV2, top-k 2048, smoothed over 100 steps. This is distinct from the paper's GLM-5.1 trace. The blog's deployment examples configure cache capacities 4096 or 6144 slots and host/device capacity ratios 8 or 10. Its `--max-running-requests 480` is a server limit, not evidence of a 480-request batch in every decode kernel. The headline 256-concurrency comparison is an 8-H200 deployment.

## Official implementation guide: units

The [SGLang HiSparse guide](https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/hisparse_guide.mdx) defines `device_buffer_size` as token slots **per request**, `top_k` as entry count, `host_to_device_ratio` as a pool-capacity ratio, and `swap_in_block_size` as CUDA threads (example: 960). These are neither disk-block sizes nor miss probabilities. The prose's “4KB tokens” wording is dimensionally misleading; use the explicit slot definition. Its benchmark example specifies 200 prompts and maximum concurrency 200, with 40000 input and 20000 output tokens; this is an example configuration, not per-GPU kernel-batch evidence.

## Derived benchmark mapping and proposed parameters

The following arithmetic and benchmark recommendations are our derivation, not additional experimental results from HiSparse.

Let `request_batch = N` mean requests represented in **one GPU's one layer invocation**, `top_k = K`, and `misses_per_request = m`. A synthetic iteration contains `N * m` missing logical KV records. With a target rate `r`, rounding per request gives `m = round(K*r)` and an effective rate `m/K`.

For K=2048, the measured paper means map to:

| Trace mean | Mean records (`2048*r`) | Rounded synthetic m | Effective synthetic rate |
|---|---:|---:|---:|
| 6.7% | 137.216 | 137 | 6.689453125% |
| 13.4% | 274.432 | 274 | 13.37890625% |
| 30% | 614.4 | 614 | 29.98046875% |

For a fixed-count-per-request synthetic model, explicit `misses_per_request` makes the assumption clear; retain `target_miss_rate` and `effective_miss_rate` separately. The accompanying `hisparse-derived-workload-profile.json` instead approximates a batch mean with `round(N*K*r)`, avoiding cumulative per-request rounding. These are different synthetic assumptions, and neither substitutes for an actual miss trace. A reasonable paper-informed kernel batch sweep is 1, 4, 16, 64, matching Fig. 7's labeled scale. These are selected representative points; axis labels alone do not establish every underlying sampled point. Use the official microbenchmark implementation if exact sweep reproduction is required.

Do not automatically assign the end-to-end 256 concurrency to a single GPU. A uniform DP=8 mapping would imply approximately 32 requests/GPU, but that requires verified parallelism and balanced active scheduling; total concurrency alone cannot establish it.

A missing logical KV record is not inherently a 4KiB SSD read. Record bytes depend on model, dtype, KV representation, and device partitioning. Physical reads additionally depend on alignment, layout, block sharing, and coalescing. If this benchmark deliberately stores one logical record per 4KiB record, state that storage-layout assumption and report physical bytes separately. Applying the CPU→GPU miss workload to SSD→GPU is a proposed tier substitution experiment, not reproduction of HiSparse's original storage path.
