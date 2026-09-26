# 发布范围

仓库当前只发布可复核的 GDS 与公开 Tutti v0.1.1 关键对照。

## 提交内容

- benchmark 源码、workload/profile 脚本和参数配置；
- 公开 Tutti 构建、ABI 预检和比较表脚本；
- `results/key-comparison-cb-20260926/` 中的精选 CSV、日志、配置和小型元数据；
- 依赖、运行和负载语义文档。

## 不提交内容

- 16 GiB 数据文件、trace.bin、build、`.venv` 和缓存；
- CUDA、cuFile、Tutti 或 daemon 的源码副本、动态库、可执行文件和内核模块；
- 旧部署适配器、旧完整 Tutti 结果和一次性调试文件；
- 任何无法通过数据校验或 ABI 检查的结果。

根目录 `.gitignore` 使用发布白名单保护结果目录；新增结果前应先确认文件类型和大小，再显式加入白名单。

发布前检查：

```bash
python3 -m compileall -q src tools
python3 tools/verify_key_comparison.py
git diff --check
git ls-files | rg '(^|/)(build|third_party|trace\\.bin|.*\\.so$|.*\\.ko$)' && exit 1 || true
```

公开仓库地址为 [GPU-Companion-File-System/hisparse_io](https://github.com/GPU-Companion-File-System/hisparse_io)。项目许可证仍由维护者决定。
