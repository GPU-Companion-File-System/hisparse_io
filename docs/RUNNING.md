# 运行与复核

从项目根目录执行。先按 README 安装 Python 包和构建 benchmark。
不需要 GPU 的统计复核使用 `tools/reproduce_results.py`，不会挂载盘或启动 daemon。

## 生成新 trace，复用实验数据

以下仅生成 trace 和元数据，不读写 NVMe 数据文件，也不需要 GPU：

```bash
RUN=results/NEW-PROFILE-RUN
.venv/bin/python src/prepare_profile_trace.py \
  --profile configs/hisparse-profile.json \
  --source-workload results/run-20260907-101847-hisparse/workload.json \
  --run-dir "$RUN" --phase-design ab
```

`RUN` 必须不存在。数据文件路径和 SHA-256 从 `--source-workload` 继承；
该文件是已知数据集的清单，不代表数据文件已经存在。新 trace 约 148 MB，被 Git 忽略。
若要求再生与归档完全相同的输入清单，请把 `--profile` 改为归档里的 `profile.json`。

如需从零准备数据，先在专用 NVMe ext4 文件系统上选择一个尚不存在的文件：

```bash
mkdir -p results/NEW-DATASET
.venv/bin/python src/prepare_workload.py \
  --data /YOUR_EXPERIMENT_MOUNT/NEW-DATA.bin \
  --run-dir results/NEW-DATASET
```

该命令实际写满并 fsync 默认 16 GiB 数据文件，拒绝覆盖；还会生成早期默认参数的 trace。
接着以 `results/NEW-DATASET/workload.json` 为 `--source-workload`，
运行 `prepare_profile_trace.py` 才得到新的 HiSparse 参考参数 trace。
数据准备需先正确挂载 NVMe ext4，脚本限制占用不超过当前可用空间的 20%。

## 核对本机运行配置

运行脚本会控制真实设备，以下值必须对应同一块空闲实验盘：

1. `src/run_abba_continuation.py`：`BDF`、`SERIAL`、`UUID`、`MOUNT`、`SHARED_BUILD`、`SHARED_CUDA`、`SHARED_LD`。
2. `workload.json`：`data_path`、`data_bytes`、`data_sha256`。
3. 将 `configs/daemon.example.yaml` 保存为新 `RUN/daemon-cb.yaml`，填写同一 BDF、挂载点和项目内绝对 `view_root`。
4. 脚本目前固定物理 GPU 0、daemon accelerator/device ID 0、端口 50173；迁移时要一起核对。
5. `configs/cufile.json` 禁止 compat 回退；运行器分别设置 A1/A2 日志目录。

`auto_mount: true` 是此部署 daemon 的要求；由 daemon 接管 Tutti 阶段的挂载和卸载。
上次测量时的 daemon 配置保存在结果目录，仅作为历史证据，不应未经核对直接用于其他主机。

## 当前 zfw 顺序 AB 预检

迁移到当前 zfw ABI-2 时，使用 `tools/run_zfw_ab.py` 做一次 A→B 顺序预检：

```bash
canhazgpu run --gpu-ids 0 --nonblock --timeout 30m \
  --note hisparse-zfw-ab -- \
  .venv/bin/python tools/run_zfw_ab.py \
  --run-dir results/NEW-RUN \
  --gds-data /STANDARD-NVME/path/data.bin \
  --tutti-data /mnt/snvme/gpu0/ssnvme2/data.bin
```

该 runner 不重启共享 zfw daemon，并要求两份确定性数据文件 SHA-256 相同。
当前主机的 cuFile 不能注册 snvme；若 A 首个 batch 失败，应保留失败日志，
单独验证 B 的 zfw 数据路径，不能计算 GDS/Tutti 加速比。配置模板见
`configs/tutti-zfw-local-nvme.yaml`。

## 公开 Tutti v0.1.1 ABI 1

公开版本必须与 ABI 1 的 `snvme-core.ko`、`snvme.ko` 和公开 daemon 成套运行。
本机已验证的命令和结果保存在
`results/public-v011-cb-20260926/`；该次严格对照使用历史 GDS 的
`0000:cb:00.0` 与公开 Tutti 的 `/dev/snvme0n1`，公开 Tutti 的 2,544 行全部通过 GPU 数据校验。

GDS 阶段应按物理 PCI BDF 选择普通 NVMe。zwh 历史盘是
`0000:cb:00.0`，当前动态设备名为 `/dev/nvme1n1`，并且需要以
`mount -t ext4 -o data=ordered` 挂载。当前主机在该盘上仍出现
`cuFileBatchIOSubmit` 5035 和 nvidia-fs DMA map failure，因此没有公开版本的
GDS/Tutti 加速比结果。

## 历史完整四阶段

配置核对完毕后：

```bash
canhazgpu run --gpu-ids 0 --nonblock --timeout 30m \
  --note hisparse-io-abba -- \
  .venv/bin/python src/run_profile_abba.py --run-dir "$RUN"
python3 src/audit_abba.py --run-dir "$RUN"
.venv/bin/python src/analyze_abba.py --run-dir "$RUN"
```

历史运行顺序为 GDS A1 → Tutti B1/B2 → GDS A2，使用同一 trace 和数据文件。
脚本按 BDF、序列号和文件系统 UUID 核对目标；在 GDS 阶段使用标准 nvme，在 Tutti 阶段使用现有 snvme。
会做设备绑定切换、挂载及本实验 daemon 启停；不修改或重载内核模块，不停止原共享 daemon。
正常完成会恢复初始绑定状态。所有输出拒绝覆盖，失败后先检查操作日志与设备状态，再决定恢复步骤。

## 结果与历史入口

新运行默认全部被 Git 忽略。要发布新的关键结果，按 `docs/PUBLISHING.md` 的保留规则逐项增加 `.gitignore` 白名单。

`run_abba_continuation.py` 的独立 CLI 和 `audit_abba.py` 的旧格式分支仅保留历史用途；
部分旧分支需要未发布的早期结果。当前支持的发布工作流是 `prepare_profile_trace.py` →
`run_profile_abba.py` → `audit_abba.py` → `analyze_abba.py`。
