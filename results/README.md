# 精选实验结果

本次发布只保留 **2026-09-07 的 HiSparse 参考参数完整 A1/B1/B2/A2 实验**：
[报告](run-20260907-101847-hisparse/REPORT.md)。测量日期与仓库整理日期不同；这些记录不表示服务器当前状态。

| 保留内容 | 原因 |
|---|---|
| `raw-A1.csv`、`raw-B1.csv`、`raw-B2.csv`、`raw-A2.csv` | 未筛选的完整原始轮次，含预热和边界检查 |
| `analysis/` 中 CSV、报告、PNG、PDF | 可读结果、逐阶段漂移、图表；`all-rounds.csv` 是便于阅读的合并副本 |
| `profile.json`、`workload.json`、`configuration-table.csv` | 参数语义、取整、固定种子与数据/trace 哈希 |
| `operations.json`、`phase-audit.json`、`verification.json` | 四阶段顺序、身份、路径与验证记录 |
| `logs/A1.log` 等、daemon 日志和两个 cuFile 日志 | 支撑完成状态、实际设备及禁用回退的结论 |
| `cufile-A1.json`、`cufile-A2.json`、`daemon-cb.yaml` | 测量时实际使用的配置，不是可直接迁移的模板 |
| `environment-*.json`、`workflow-provenance.json` 等小型清单 | 当时环境和软件指纹；绝对路径是历史来源标识 |
| 两份参数参考文件 | 说明 HiSparse 依据及合成负载的边界 |

不发布 trace.bin（147,965,856 字节）、16 GiB NVMe 数据文件、早期失败运行、
修复调试目录和一次性进程 PID 记录。它们在本机保留，没有被删除。
数据文件由 `src/prepare_workload.py` 确定性生成，trace 由 `src/prepare_profile_trace.py` 再生。

`tools/reproduce_results.py` 在临时目录再生 trace、验证归档输入哈希、运行路径审计并重算表格。
它不读取清单里记录的外部绝对路径，也不使用 GPU/SSD。
清单中的软件源码哈希描述测量时版本；后续整理不重写原始指纹来伪装版本一致。

所有发布的历史结果保持原始字节，`.gitattributes` 禁止对 results 自动转换行尾。
新运行和未列出的文件默认被忽略；允许发布的具体文件由根目录 `.gitignore` 明确列出。
