#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/.." && pwd)
SRC=${TUTTI_SOURCE_DIR:-"$ROOT/third_party/Tutti-v0.1.1"}
BUILD=${TUTTI_BUILD_DIR:-"$ROOT/build/tutti-v011"}
CUDA=${CUDA:-/usr/local/cuda-12.8}
PIN=38c8a68ab99c47a9a31f120b1018b6a7e01734d1
if [[ -e "$SRC" && ! -e "$SRC/.git" ]]; then
  echo "TUTTI_SOURCE_DIR exists but is not a Git checkout: $SRC" >&2
  exit 1
fi
if [[ ! -e "$SRC" ]]; then
  git clone --depth 1 --branch v0.1.1 https://github.com/xPU-IO/Tutti.git "$SRC"
fi
[[ $(git -C "$SRC" rev-parse HEAD) == "$PIN" ]] || { echo 'Wrong Tutti commit' >&2; exit 1; }
[[ -z $(git -C "$SRC" status --porcelain) ]] || { echo 'Tutti source is modified; refusing' >&2; exit 1; }
cmake -S "$SRC" -B "$BUILD" \
  -DCMAKE_CUDA_COMPILER="$CUDA/bin/nvcc" -DCUDAToolkit_ROOT="$CUDA" \
  -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES:-90}" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DTUTTI_BUILD_HARDWARE_TESTS=OFF -DTUTTI_BUILD_KERNEL_MODULE=OFF \
  -DCMAKE_PROJECT_Tutti_INCLUDE="$ROOT/cmake/tutti-v011-hook.cmake" "$@"
cmake --build "$BUILD" --parallel "${BUILD_JOBS:-8}"
ctest --test-dir "$BUILD" --output-on-failure
