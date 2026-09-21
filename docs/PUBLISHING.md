# Git 与发布准备

整理日期：2026-09-21。整理前项目根目录没有 Git 仓库；本次在本地初始化 `main`。
组织私有仓库为 [GPU-Companion-File-System/hisparse_io](https://github.com/GPU-Companion-File-System/hisparse_io)，主分支为 `main`。
2026-09-21 按用户要求创建 private 仓库并准备首次提交。项目许可证仍待维护者确定。
`preparation-checks.json` 是创建远端之前的准备阶段记录，其中的 Git/remote 状态仅描述当时状态。

## 发布范围

| 内容 | 处理 |
|---|---|
| README、参数定义、依赖/运行说明、复核脚本 | 提交 |
| 两个 C++ benchmark、公共头文件、Makefile | 提交 |
| 活跃的 trace 生成、四阶段运行、审计和分析脚本 | 提交 |
| `run_abba_continuation.py` | 作为活跃运行器依赖的设备/部署辅助模块提交；旧 CLI 标为历史入口 |
| `configs/` 中负载、cuFile 与 daemon 模板 | 提交 |
| 最新完整实验的原始 CSV、图表、配置、验证证据 | 明确白名单提交 |
| 大型 trace、实际 NVMe 数据、build、.venv、__pycache__ | 忽略，本地保留 |
| third_party 下 Tutti 源码、部署快照、CUDA 和动态库 | 忽略，引用外部安装 |
| 旧 CMake smoke、旧 smoke runner、一次性 udev 规则、旧恢复脚本 | 不纳入首批发布，本地保留 |
| STORAGE.md 和旧失败/调试结果 | 不纳入首批发布；README/RUNNING 提供当前运行说明 |

结果约几 MB，不需要为大文件配置 Git LFS。具体大小和逐文件 SHA-256 见
`docs/publication-manifest.json`；该清单描述首次提交的发布文件内容，排除清单本身和最终准备检查记录以避免自引用。

历史证据中的本机路径、BDF、序列号与哈希有助于复核，保持原样；它们不是通用运行配置。
新的 daemon 模板使用显式占位符，活跃运行器从 `configs/cufile.json` 读取配置，
不再依赖未发布的早期结果目录。

## 本地检查

```bash
git status --short
git diff --cached --stat
git diff --cached --check
git ls-files
```

从暂存区导出到临时干净目录，在该目录运行 CPU-only 结果复核工具。
本次不会重新运行 GPU 性能测试、修改磁盘绑定或重建共享依赖。

## 远端与后续提交

`origin` 使用 SSH：`git@github.com:GPU-Companion-File-System/hisparse_io.git`。
首次提交使用之前复核的白名单内容；不包含依赖库副本、build 或大型 trace。
`publication-manifest.json` 的时间点为首次提交前，不在提交内部预先声称推送成功。

后续变更先检查暂存差异，再提交并推送：

```bash
git diff --cached --check
git diff --cached --stat
git commit
git push origin main
```

增加关键实验时需同步更新 `.gitignore` 白名单；历史原始数据、日志和哈希不随代码更新改写。
