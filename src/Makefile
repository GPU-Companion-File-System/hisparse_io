CUDA ?= /usr/local/cuda-12.8
CXX ?= g++
# Empty for readable shared installations; override to sudo -n on the original host.
TUTTI_BUILD_PREFIX ?= sudo -n
CPPFLAGS += -I$(CUDA)/include
CXXFLAGS += -O2 -std=c++17 -Wall -Wextra
LDFLAGS += -L$(CUDA)/lib64 -Wl,-rpath,$(CUDA)/lib64

../build/gds_bench: gds_bench.cpp bench_common.h
	mkdir -p $(@D)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) gds_bench.cpp $(LDFLAGS) -lcufile -lcudart -o $@

# Reuse the server's shared build directly; do not duplicate its dependencies.
SHARED_SRC ?= /home/zwh/lmcache-dev/csrc/GeminiFS
SHARED_LIB ?= /home/zwh/lmcache-dev/.build/vllm027-torch213-cu130/geminifs/lib
SHARED_CUDA ?= /home/zwh/.venvs/lmcache-mooncake-latest/lib/python3.12/site-packages/nvidia/cu13
SHARED_DEPS ?= /home/zwh/anaconda3/lib
# Keep the previous executable name compatible with the same shared dependencies.
../build/tutti_shared_bench ../build/tutti_deployed_bench: tutti_deployed_bench.cpp bench_common.h Makefile
	mkdir -p $(@D)
	$(TUTTI_BUILD_PREFIX) $(CXX) -O2 -std=c++20 -Wall -Wextra \
	 -I$(SHARED_CUDA)/include -I$(SHARED_CUDA)/include/cccl \
	 -I$(SHARED_SRC)/device_manager/include -I$(SHARED_SRC)/coordinator/include \
	 -I$(SHARED_SRC)/memory/include -I$(SHARED_SRC)/nvme_storage/include \
	 -I$(SHARED_SRC)/io_engine/include -I$(SHARED_SRC)/block_storage/include \
	 -I$(SHARED_SRC)/backends/local/nvme/libnvm/include -I$(SHARED_SRC)/backends/local/nvme/libnvm/src \
	 tutti_deployed_bench.cpp -L$(SHARED_LIB) -L$(SHARED_CUDA)/lib \
	 -Wl,-rpath,$(SHARED_LIB):$(SHARED_CUDA)/lib:$(SHARED_DEPS) \
	 -Wl,-rpath-link,$(SHARED_LIB):$(SHARED_CUDA)/lib:$(SHARED_DEPS) \
	 -ltutti_device_manager -ltutti_memory -ltutti_io_engine_local_nvme -ltutti_nvme_storage -lnvm -lcudart -o $@
