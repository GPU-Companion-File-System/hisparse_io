# 发布结果

仓库只保留一个性能结果目录：[`key-comparison-cb-20260926`](key-comparison-cb-20260926/)。其中包括 GDS A1/A2 的成功原始 CSV、cuFile 配置和日志，公开 Tutti v0.1.1 的完整原始 CSV，以及统一的 `comparison.csv`、输入哈希和 `verification.json`。

目录不包含 16 GiB 数据文件、147 MB trace、build、虚拟环境、动态库、内核模块或 daemon 二进制。原始 CSV 的机器绝对路径只作为采集 provenance，不是运行要求。

GDS 与 Tutti 的采集日期不同，但配置、数据和 trace 对齐；这组数据用于直接的同盘微基准对照。旧的 Tutti 完整实验、旧部署适配器和临时 ABI 迁移结果不属于发布内容。
