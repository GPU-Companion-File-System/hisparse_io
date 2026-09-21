# HiSparse-pattern IO benchmark

比较 **GDS 与 Tutti 将离散 4 KiB 数据从 NVMe SSD 读入 GPU HBM** 的延迟和吞吐量。
负载规模参考 HiSparse 的 TopK 和缓存缺失率；这是合成 IO 微基准，尚未接入真实 HiSparse / SGLang 模型推理。

## 实验做了什么

- `top_k=2048`；本地请求 batch 为 `1 / 4 / 16 / 64`；参考 miss rate 为 `6.7% / 13.4% / 30%`。
- 每轮读数：`round(batch × top_k × miss_rate)`。每个模拟缺失项对应一个 4 KiB SSD 读。
- 从 16 GiB 确定性数据文件中选择互不重复的随机块，目标为 256 MiB GPU HBM 中互不重叠的随机槽位。
- 两后端共享同一 trace、GPU 和 SSD；逻辑在途 IO 上限 256，16 个窗口，每窗口最多 16 IO。
- A1 → B1 → B2 → A2，A 为 GDS，B 为 Tutti；每阶段每配置 10 轮预热、200 正式轮和前后边界检查。
- 计时从首次提交前到最后完成被主机观察；每轮预填和数据校验在计时外。

没有执行真实 TopK、LRU、逐层推理或请求调度，也没有复现跨步访问局部性。
HiSparse 原始缺失补入路径是主机内存 → GPU；这里把缺失项映射到 SSD，是待研究的存储层扩展假设。
字段、取整方式和参考参数来源见 [WORKLOAD_SEMANTICS.md](WORKLOAD_SEMANTICS.md)。

## 保留的关键结果

归档实验日期：**2026-09-07**。以下为参考 miss rate **13.4%** 的合并两阶段 p50：

| 本地 batch | 每轮 4 KiB 读数 | GDS p50 | Tutti p50 | GDS/Tutti |
|---:|---:|---:|---:|---:|
| 1 | 274 | 1.531 ms | 0.319 ms | 4.80× |
| 4 | 1,098 | 5.618 ms | 0.934 ms | 6.01× |
| 16 | 4,391 | 24.293 ms | 3.450 ms | 7.04× |
| 64 | 17,564 | 159.541 ms | 13.427 ms | 11.88× |

四阶段共 9,600 条正式样本，含预热和边界检查的 10,176 轮均通过数据校验。
这些是当前硬件、适配器和提交策略的结果；GDS 存在长尾及阶段漂移，不能解释为 HiSparse 端到端加速或两个后端的性能上限。

[完整报告](results/run-20260907-101847-hisparse/REPORT.md) ·
[全部配置比较](results/run-20260907-101847-hisparse/analysis/comparison.csv) ·
[分阶段统计](results/run-20260907-101847-hisparse/analysis/phase-summary.csv) ·
[结果保留规则](results/README.md)

![四阶段延迟，按参考 miss 场景分列](results/run-20260907-101847-hisparse/analysis/phase-latency.png)

## 仓库内容

| 路径 | 用途 |
|---|---|
| `src/gds_bench.cpp`、`src/tutti_deployed_bench.cpp`、`src/bench_common.h` | 两个后端及公共 trace、计时、校验逻辑 |
| `src/prepare_workload.py`、`src/prepare_profile_trace.py` | 确定性数据和 trace 生成 |
| `src/run_profile_abba.py` | 完整四阶段运行入口 |
| `src/run_abba_continuation.py` | 运行入口复用的设备/部署定义；保留早期续跑实现 |
| `src/audit_abba.py`、`src/analyze_abba.py` | 路径审计、CSV 校验、统计和绘图 |
| `configs/` | HiSparse 参考负载、严格 cuFile 配置、daemon 配置模板 |
| `tools/reproduce_results.py` | 不使用 GPU，从归档 CSV 和再生 trace 复核结果 |
| `results/` | 精选的一次完整实验及参数依据；不存大型 trace 或数据文件 |
| `docs/` | 依赖、运行方法和发布范围 |

## 先复核结果：不需要 GPU 或 SSD

使用 Python 3.12 和实验时的直接依赖版本：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/reproduce_results.py --output-dir build/result-review
```

该命令重新生成约 148 MB 的 trace，验证其 SHA-256 与归档值一致，检查四阶段原始 CSV 和路径日志，再重算表格和图表。
输出目录必须尚不存在。原始归档保持不变；图像文件不保证跨平台字节一致，CSV 数值会与归档表格比较。
这一步只验证记录和统计链条，不重新证明实际硬件的数据路径。

## 构建与运行

需要 Linux、NVIDIA GPU / CUDA / GDS 和与 Tutti 适配器匹配的部署。依赖从已有安装引用，不将 `.so`、CUDA、虚拟环境或第三方源码放进本仓库。

```bash
make -C src ../build/gds_bench CUDA=/path/to/cuda-with-gds
make -C src ../build/tutti_shared_bench \
  SHARED_SRC=/path/to/matching/Tutti-source \
  SHARED_LIB=/path/to/matching/Tutti-build/lib \
  SHARED_CUDA=/path/to/cuda13 \
  SHARED_DEPS=/path/to/dependency-libs \
  TUTTI_BUILD_PREFIX=
```

原实验使用带本地修改的 Tutti 部署，不能假定最新上游源码可直接替换。
Makefile 默认保留原服务器的共享路径；上面的参数允许覆盖编译路径。
运行脚本中的设备 BDF、序列号、UUID、挂载点和共享库路径仍是原机器配置，迁移时必须一起调整。

**四阶段运行会挂载实验文件系统并切换目标盘的 nvme/snvme 驱动绑定。**
仅用于核对过身份、空闲且专供实验的盘；不会修改或重载内核模块。
本服务器所有 GPU 工作须通过 `canhazgpu` 预约。完整步骤见 [运行说明](docs/RUNNING.md)。

## 依赖与发布状态

- Tutti：外部匹配源码、用户态库及 daemon；CUDA/GDS：系统或共享安装。
- NumPy/Matplotlib：通过 `requirements.txt` 安装。
- HiSparse/SGLang：作为参数和设计参考，本实验不导入或启动它们。

详细版本依据和限制见 [依赖说明](docs/DEPENDENCIES.md)。

组织私有仓库：[GPU-Companion-File-System/hisparse_io](https://github.com/GPU-Companion-File-System/hisparse_io)，主分支为 `main`。
项目许可证尚未确定；当前没有添加开源许可证。
发布范围与本地保留项见 [发布清单](docs/PUBLISHING.md)。
