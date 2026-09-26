# 公开 Tutti v0.1.1 迁移状态（2026-09-26）

**ABI 1 全栈切换和 Tutti 硬件读验证已完成；GDS 在 zwh 同一块普通 NVMe 上仍被当前 nvidia-fs DMA 映射阻塞。**

## 确定版本

- 上游：`https://github.com/xPU-IO/Tutti`
- tag：`v0.1.1`
- commit：`38c8a68ab99c47a9a31f120b1018b6a7e01734d1`
- 上游工作树无修改；没有将旧 fork 的头文件或 `.so` 混入构建。
- CUDA 12.8.93；本机已有 gRPC / protobuf / yaml-cpp。

新增适配器 `src/tutti_public_bench.cpp` 仅调用公开 `StorageRuntime` 与 `presets::make_local_nvme_runtime`，
文件 URI 的打开、extent 解析与内存注册交给公开 runtime；不依赖旧 `nvmeservice_backed_registry.h`。
它保留当前 16 窗口、每窗口 16 IO 的调度策略，并记录公开 DataPath 的提交/内核启动计数。
该适配器已在真实 snvme 设备上完成读验证。

API 依据：
- [公开 preset](https://github.com/xPU-IO/Tutti/blob/v0.1.1/tutti/include/tutti/presets/local_nvme.h)
- [公开示例](https://github.com/xPU-IO/Tutti/blob/v0.1.1/examples/layerwise_kv_overlap/layerwise_kv_overlap.cpp)

## 已通过的步骤

```bash
# 用户态/daemon 与无硬件测试
CUDA=/usr/local/cuda-12.8 tools/build_public_tutti.sh

# ABI 1 模块构建（当前内核 5.15.0）
cmake -S third_party/Tutti-v0.1.1 -B build/public-v011-module \
  -DTUTTI_BUILD_KERNEL_MODULE=ON -DTUTTI_P2P_BACKEND=nvidia \
  -DSNVME_KERNEL_VERSION=5.15.0-public \
  -DSNVME_P2P_INCLUDE_DIR=/usr/src/nvidia-610.43.02/nvidia-peermem
cmake --build build/public-v011-module --parallel 8
```

用户态构建随后执行上游 16 项 CTest。模块构建产物为
`build/public-v011-module/module/snvme-core.ko` 和 `snvme.ko`。
脚本要求 `cmake>=3.19`（使用 DEFER），gRPC/Protobuf/yaml-cpp 的开发头和 CMake 导出可用。
缺少 gRPC 时构建会明确失败，不接受静默关闭 NVMe 路径的 stub 构建。

## ABI 1 切换结果

切换后 `NVM_GET_DEV_INFO` 返回：

```json
{"abi_version":1,"expected_abi":1,"capabilities":31,"disk_name":"snvme2n1","block_size":4096,"queue_depth":1024,"bar0_size":32768}
```

v0.1.1 的 [UAPI](https://github.com/xPU-IO/Tutti/blob/v0.1.1/tutti/include/uapi/tutti_snvme.h)
定义 `TUTTI_SNVME_ABI_VERSION=1`，其
[libnvm](https://github.com/xPU-IO/Tutti/blob/v0.1.1/tutti/device_manager/nvme/libnvm/src/linux/device.cpp)
要求内核与用户态版本相等。跳过检查或换用其他版本 libnvm 会失去“原版公开 v0.1.1”这一条件。

公开 daemon 已使用与原 zfw 配置相同的四个 BDF 和挂载点重新启动，四块 snvme 均挂载成功。
用于关键对照的公开 v0.1.1 benchmark 在历史 GDS 同一物理盘 `0000:cb:00.0` 上运行，
设备节点为 `/dev/snvme0n1` / `/dev/ssnvme0`，完成 2,544 行记录，所有 GPU 数据校验通过。

完整对照见 [`results/public-v011-cb-20260926/README.md`](../results/public-v011-cb-20260926/README.md)。

GDS 使用 zwh 历史实验的同一物理普通 NVMe `0000:cb:00.0`（当前设备名
`/dev/nvme1n1`，挂载选项 `data=ordered`）。当前重跑时 cuFile 文件注册成功，
但首个 batch 仍返回 5035；内核报告该 BDF 的 DMA map failure。因此关键对照中的
GDS 数值明确引用 2026-09-07 已成功完成的 A1+A2 历史样本，而不是伪造新的 GDS 测量。

## 原结果处理

旧 zwh 结果继续保留并在 README 标为历史数据；当前关键对照归档在
`results/public-v011-cb-20260926/`。本轮没有删除旧结果、修改历史哈希或重写 Git 历史。

证据：[验证清单](../results/public-v011-preflight-20260925/verification.json)、
[CTest](../results/public-v011-preflight-20260925/ctest.log)、
[ABI](../results/public-v011-preflight-20260925/abi.json)。
