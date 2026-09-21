# 外部依赖与版本依据

本仓库提交自有 benchmark、配置和结果；通过安装路径引用依赖，不提交第三方源码、构建目录或动态库。

| 依赖 | 用途 | 获取或引用方式 |
|---|---|---|
| CUDA 12.8 与 GDS/cuFile | GDS batch API、GPU buffer | 系统安装，Makefile 的 `CUDA` 指向含 `include/cufile.h` 和 `lib64/libcufile.so` 的目录 |
| 匹配的 Tutti 部署 | GPU NVMe IO、队列、注册内存、FIEMAP、独立 daemon | `SHARED_SRC` / `SHARED_LIB`；原实验使用已有共享构建 |
| CUDA runtime 13 | Tutti 部署配套 CUDA 运行库与头文件 | `SHARED_CUDA`，不复制进仓库 |
| gRPC、protobuf、Abseil、yaml-cpp 等 | Tutti 的间接动态库依赖 | 匹配部署的依赖目录 `SHARED_DEPS` |
| NumPy 1.26.4、Matplotlib 3.10.0 | 确定性 trace、分析和绘图 | Python 3.12 + `requirements.txt`；仅固定直接依赖 |
| canhazgpu | 当前服务器的 GPU 预约 | 主机已有工具；不作为 Python 包或第三方源码打包 |
| HiSparse / SGLang | 参数和机制参考 | 不需要安装；尚未做模型集成 |

Tutti 上游参考：[xPU-IO/Tutti](https://github.com/xPU-IO/Tutti)。
实验实际依赖的是本机带修改的 fork；早期部署记录的基准 commit 为
`aedad8a689f73f244571eb4879ea35ebed33ac8b`，记录明确标注 `local_modifications=true`。
该 commit **不足以重建全部本地修改**，不能当作精确的可复现 release pin。

实验当时的实际 `.so`、daemon 和 benchmark 二进制 SHA-256 保存在
[environment-before.json](../results/run-20260907-101847-hisparse/environment-before.json)，
[environment-after.json](../results/run-20260907-101847-hisparse/environment-after.json)记录运行后未变更检查。
归档的 [workflow-provenance.json](../results/run-20260907-101847-hisparse/workflow-provenance.json)
是测量时源码指纹；它不会随着仓库整理而重写。本次整理只调整配置位置、构建输出目录和文档/复核工具；
两个 benchmark C++ 文件及公共头文件保持测量时版本。

## 原服务器安装位置

这些路径只用于说明原实验的部署，不代表发布仓库包含对应内容：

```text
源码       /home/zwh/lmcache-dev/csrc/GeminiFS
构建       /home/zwh/lmcache-dev/.build/vllm027-torch213-cu130/geminifs
CUDA 13    /home/zwh/.venvs/lmcache-mooncake-latest/lib/python3.12/site-packages/nvidia/cu13
间接依赖   /home/zwh/anaconda3/lib
```

Makefile 可覆盖上述编译路径；运行路径仍需在 `src/run_abba_continuation.py` 中同步修改。
原服务器目录访问需要 `sudo`，因此保留 `TUTTI_BUILD_PREFIX=sudo -n` 默认值；
普通可读安装可传 `TUTTI_BUILD_PREFIX=`。运行脚本原本用于受控共享实验服务器，并非通用部署安装器。

## 复现范围

- **统计复核**：仅依靠提交的配置、CSV、日志和 Python 包，可以再生相同 trace 并复核数值。
- **硬件重跑**：还需匹配 Tutti 部署、CUDA/GDS、GPU/NVMe 和驱动环境。当前不承诺从上游最新源码重建原部署。
- 暂不添加 Git submodule：精确部署包含尚未单独发布的本地修改，错误地固定上游 commit 会误导复现。
- NVIDIA 软件通过正常安装提供；本仓库不重新分发。项目自身许可证待维护者确定，本次未添加许可证声明。
