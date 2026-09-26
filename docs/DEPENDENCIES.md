# 依赖

仓库只提交 benchmark、配置、脚本和精选结果；第三方源码、动态库、构建目录和数据文件均从外部安装路径引用。

| 依赖 | 用途 | 方式 |
|---|---|---|
| CUDA 与 GDS/cuFile | GDS batch API 和 GPU buffer | 系统安装；`make -C src gds CUDA=...` |
| xPU-IO/Tutti v0.1.1 | 公开 Tutti runtime、daemon 和 snvme UAPI | `tools/build_tutti_v011.sh` 固定 commit `38c8a68ab99c47a9a31f120b1018b6a7e01734d1` |
| gRPC、protobuf、yaml-cpp、Abseil | Tutti 构建依赖 | 系统或共享安装，不复制进仓库 |
| NumPy 1.26.4 | trace 和统计 | `requirements.txt` |
| canhazgpu | GPU 预约 | 主机工具，不是项目依赖包 |

公开 Tutti benchmark 只调用 v0.1.1 的 `StorageRuntime`、`LocalNvmePreset`、公开 UAPI 和公开 daemon；没有额外的部署头文件依赖。构建脚本默认关闭内核模块构建，因为本仓库不负责安装或替换内核模块。

公开 Tutti 和 snvme 内核端必须使用相同 ABI。`preflight_tutti_v011.py` 只做只读 UAPI 检查；ABI、BDF、块设备和文件 backing device 不匹配时应停止运行。

HiSparse/SGLang 只作为参数和机制参考，本项目没有导入或启动模型。
