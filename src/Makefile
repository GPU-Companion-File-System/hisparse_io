CUDA ?= /usr/local/cuda-12.8
CXX ?= g++
CPPFLAGS += -I$(CUDA)/include
CXXFLAGS += -O2 -std=c++17 -Wall -Wextra
LDFLAGS += -L$(CUDA)/lib64 -Wl,-rpath,$(CUDA)/lib64

.PHONY: gds

gds: ../build/gds_bench

../build/gds_bench: gds_bench.cpp bench_common.h
	mkdir -p $(@D)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) gds_bench.cpp $(LDFLAGS) -lcufile -lcudart -o $@

# The public Tutti v0.1.1 benchmark is built by tools/build_tutti_v011.sh,
# which configures it against the pinned upstream source and public API.
.PHONY: tutti-v011

tutti-v011:
	../tools/build_tutti_v011.sh
