# 构建、预检与运行

所有 GPU 命令都通过 `canhazgpu` 预约。仓库脚本不会安装内核模块、重载驱动、格式化磁盘或复制依赖库。

## 1. 生成 workload

选择已经挂载且专供实验的 NVMe ext4 文件系统，生成一次不会覆盖的数据文件：

```bash
python3 src/prepare_workload.py --data /MOUNT/bench.bin --run-dir build/workload-base
python3 src/prepare_profile_trace.py \
  --profile configs/hisparse-profile.json \
  --source-workload build/workload-base/workload.json \
  --run-dir build/workload-v011
```

生成的 `trace.bin` 和数据文件只在本机使用，不提交 Git。若只复核已提交结果，运行 `python3 tools/verify_key_comparison.py` 即可。

## 2. 构建

```bash
make -C src gds CUDA=/path/to/cuda-with-gds
CUDA=/usr/local/cuda-12.8 tools/build_tutti_v011.sh
```

构建脚本固定公开 Tutti v0.1.1，并设置 `TUTTI_BUILD_KERNEL_MODULE=OFF`。缺少 gRPC/Protobuf 或公开 daemon target 时会失败，不生成 stub benchmark。

## 3. 只读预检

```bash
python3 tools/preflight_tutti_v011.py \
  --build-dir build/tutti-v011 \
  --device /dev/ssnvme0
```

预检只读取公开 UAPI，确认 ABI 和 4 KiB block size；随后还需人工核对字符设备、块设备、文件 backing device 和 PCI BDF 属于同一块空闲实验盘。daemon 配置模板为 [`configs/daemon.example.yaml`](../configs/daemon.example.yaml)。

## 4. 运行单个后端

```bash
canhazgpu run --gpu-ids 0 --note hisparse-gds -- \
  build/gds_bench DATA TRACE build/gds.csv

canhazgpu run --gpu-ids 0 --note hisparse-tutti-v011 -- \
  build/tutti-v011/bin/tutti_v011_bench \
  DATA TRACE build/tutti-v011.csv /dev/ssnvme0 BDF BLOCKDEV
```

`DATA` 必须位于 `BLOCKDEV` 对应的文件系统中；程序会检查文件大小、BDF、ABI 和数据校验。输出 CSV 必须不存在，避免覆盖已有测量。

## 5. 生成比较表

```bash
python3 tools/make_key_comparison.py \
  --gds-a1 results/key-comparison-cb-20260926/gds-A1.csv \
  --gds-a2 results/key-comparison-cb-20260926/gds-A2.csv \
  --tutti-v011 results/key-comparison-cb-20260926/tutti-v011.csv \
  --out-dir build/key-comparison \
  --workload results/key-comparison-cb-20260926/workload.json \
  --data /MOUNT/bench.bin --trace /PATH/trace.bin \
  --bdf 0000:cb:00.0 --serial SERIAL \
  --tutti-commit 38c8a68ab99c47a9a31f120b1018b6a7e01734d1
```

脚本把 GDS A1/A2 合并为每配置 400 个样本，Tutti 使用 200 个样本，并输出 p50/p99 表。不要把失败、ABI 不匹配或数据校验失败的 CSV 混入比较。
