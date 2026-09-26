# 公开 Tutti v0.1.1 规范

- 上游仓库：`https://github.com/xPU-IO/Tutti`
- 固定 commit：`38c8a68ab99c47a9a31f120b1018b6a7e01734d1`
- benchmark：`src/tutti_v011_bench.cpp`
- 构建入口：`tools/build_tutti_v011.sh`
- 构建目录：`build/tutti-v011`
- 预检入口：`tools/preflight_tutti_v011.py`

适配器使用公开的 `presets::make_local_nvme_runtime` 打开文件、注册 GPU memory、提交 IO、等待完成并释放句柄。它保持 16 个窗口、每窗口最多 16 个请求和 256 的逻辑在途上限。

每条读请求都验证目标 GPU 槽位的确定性内容。程序检查字符设备 ABI、4 KiB 块大小、PCI BDF、文件和块设备是否来自同一 backing device；检查失败时不会提交 GPU IO。

这套实现模拟 HiSparse-derived IO 数量，不是 HiSparse 模型集成，也不实现 LRU 或 miss 生成。内核模块、daemon、文件系统挂载和 GPU 运行属于主机部署步骤，不会随仓库发布。
