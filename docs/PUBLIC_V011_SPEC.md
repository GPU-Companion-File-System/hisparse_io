# Public Tutti v0.1.1 migration and rerun

## Objective and assumptions
- User requested a new hardware experiment using public v0.1.1, not reproduction of the unpublished deployment.
- Pin tag v0.1.1 to commit 38c8a68ab99c47a9a31f120b1018b6a7e01734d1 in xPU-IO/Tutti; vendor source must remain unmodified.
- Use public StorageRuntime + presets::make_local_nvme_runtime (open file URI, register memory, submit, query/wait, release).
- Keep the existing 12 synthetic HiSparse-derived configurations, 4 KiB reads, 256 IO cap, 16-entry submissions, 200 measured rounds, identical trace across fresh A/B/B/A stages.
- This remains synthetic miss-volume IO, not a real model/TopK/LRU integration.

## Structure and commands
- cmake/public-tutti-hook.cmake: discover dependencies and attach benchmark targets to the canonical upstream root build.
- src/tutti_public_bench.cpp: public API backend; src/gds_bench.cpp remains the GDS backend.
- tools/build_public_tutti.sh: pinned checkout + canonical CMake build with kernel builds disabled.
- tests/ and upstream CTest: CPU tests; reserved short hardware smoke before full matrix.
- Build: tools/build_public_tutti.sh
- Tests: ctest --test-dir build/public-v011 --output-on-failure
- Preflight (no GPU): python3 tools/preflight_public_tutti.py --device /dev/ssnvme0
- Hardware runner remains pending until a matching kernel environment is available; no run command is claimed ready.

## Code style
Retain the existing C++17 RAII/status-check style: `if (!result.ok()) throw std::runtime_error(result.status().message());`.
Use pathlib, JSON records and exclusive output creation in Python; fail closed on device identity or path-evidence mismatch.

## Verification and boundaries
- Always: record commit, build/config hashes, dependencies and kernel ABI; reserve GPU; validate every read; preserve raw failures; verify before/after data hashes.
- Do not: replace/reload modules, stop shared services, format devices, bypass public ABI checks, or silently fall back to host-staged IO.
- Ask first if new module installation or destructive disk recovery is required.
- Old results are retired from active repo only after new results pass; retain historical Git commit, do not rewrite remote history or push without request.
- Success: clean public source build, public API hardware smoke, fresh complete validated ABBA, minimal reproducible result bundle and no unpublished dependency.

## 2026-09-25 checkpoint
Public user-space build and 16 CTest cases pass. Existing module reports ABI 2; pinned release requires ABI 1 and fails closed. No hardware run attempted. No module/device/service changes. Adapter is compile-tested, not hardware-validated. Old results retained until replacement passes.
