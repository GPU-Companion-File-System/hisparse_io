# HiSparse-pattern NVMe→GPU benchmark

本仓库比较 GDS 和公开 Tutti v0.1.1 将离散 4 KiB 数据从 NVMe SSD 读入 GPU HBM 的性能。它是合成 IO 微基准：参数参考 HiSparse 的 TopK 和 miss rate，但没有启动真实模型，也没有实现 TopK、LRU 或请求调度。

## 关键对照

唯一保留的性能结果位于 [`results/key-comparison-cb-20260926/`](results/key-comparison-cb-20260926/)。两套后端使用同一块 PCI BDF 为 `0000:cb:00.0` 的 SSD、同一 16 GiB 数据文件、同一 trace 和同一组 12 个配置。GDS 使用已成功完成的 A1/A2 样本；Tutti 使用公开上游 v0.1.1（commit `38c8a68ab99c47a9a31f120b1018b6a7e01734d1`）的完整矩阵。两组数据采集日期分别为 2026-09-07 和 2026-09-26。

参考 miss rate 13.4% 的 p50 延迟如下；加速比定义为 GDS/Tutti，数值大于 1 表示 Tutti 更快。

| 本地 batch | 每轮 4 KiB 读数 | GDS p50 | Tutti v0.1.1 p50 | GDS/Tutti |
|---:|---:|---:|---:|---:|
| 1 | 274 | 1.531 ms | 1.297 ms | 1.18× |
| 4 | 1,098 | 5.618 ms | 3.332 ms | 1.69× |
| 16 | 4,391 | 24.293 ms | 12.977 ms | 1.87× |
| 64 | 17,564 | 159.541 ms | 51.616 ms | 3.09× |

Tutti 的 2,544 条原始记录全部通过 GPU 数据校验。关键目录还包含三份原始 CSV、配置、日志、输入哈希和逐行验证元数据。

## 负载定义

- `top_k=2048`；local decode batch 为 `1 / 4 / 16 / 64`；参考 miss rate 为 `6.7% / 13.4% / 30%`。
- 每轮读取数为 `round(batch × top_k × miss_rate)`，每个读取为 4 KiB。
- 数据文件为 16 GiB，GPU 目标缓冲区为 256 MiB；随机源块和目标槽位在每轮内不重复。
- 两个后端使用相同 trace；逻辑在途 IO 上限为 256，每次提交最多 16 个 IO。
- 每个配置包含 10 次预热、200 次正式测量和前后校验记录。

字段语义和 HiSparse 参数来源见 [`WORKLOAD_SEMANTICS.md`](WORKLOAD_SEMANTICS.md) 与 [`results/hisparse-derived-workload-profile.json`](results/hisparse-derived-workload-profile.json)。

## 复核归档结果

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/verify_key_comparison.py
```

这个命令不使用 GPU、SSD、daemon 或内核模块，也不会生成大型 trace。

## 构建

GDS 使用本机 CUDA/GDS 安装：

```bash
make -C src gds CUDA=/path/to/cuda-with-gds
```

公开 Tutti v0.1.1 使用外部源码和系统依赖，不把源码、动态库或构建产物复制进仓库：

```bash
CUDA=/usr/local/cuda-12.8 tools/build_tutti_v011.sh
python3 tools/preflight_tutti_v011.py --build-dir build/tutti-v011 --device /dev/ssnvme0
```

脚本固定上游 commit，并关闭内核模块构建；运行前必须确认用户态库、daemon、snvme UAPI 和目标盘属于同一套 v0.1.1 环境。GPU 命令必须通过 `canhazgpu` 预约。硬件运行步骤见 [`docs/RUNNING.md`](docs/RUNNING.md)。

## 目录

| 路径 | 用途 |
|---|---|
| `src/gds_bench.cpp` | GDS/cuFile benchmark |
| `src/tutti_v011_bench.cpp` | 公开 Tutti v0.1.1 API benchmark |
| `src/prepare_workload.py`、`src/prepare_profile_trace.py` | 确定性数据清单和 trace 生成 |
| `tools/make_key_comparison.py` | 从三份原始 CSV 生成统一比较表 |
| `tools/verify_key_comparison.py` | 无硬件校验已提交结果 |
| `configs/`、`cmake/` | cuFile、daemon 和公开 Tutti 构建配置 |
| `results/key-comparison-cb-20260926/` | 唯一发布的性能对照 |

依赖和发布边界见 [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) 与 [`docs/PUBLISHING.md`](docs/PUBLISHING.md)。
