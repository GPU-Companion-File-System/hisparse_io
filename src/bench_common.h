#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <cuda_runtime.h>

using Clock = std::chrono::steady_clock;
inline double micros(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::micro>(b-a).count();
}
inline void cuda_check(cudaError_t e, const char* stage) {
    if(e != cudaSuccess) throw std::runtime_error(std::string(stage)+": "+cudaGetErrorString(e));
}
struct Entry { uint32_t block, slot; };
static_assert(sizeof(Entry)==8);
struct Record {
    uint32_t batch, ppm, count, phase, round;
    std::vector<Entry> entries;
};
struct Workload {
    uint32_t io_size=0, slots=0, record_count=0, seed=0;
    uint64_t data_bytes=0;
    std::vector<Record> records;
    explicit Workload(const std::string& file) {
        std::ifstream in(file,std::ios::binary);
        auto read=[&](void* dst,size_t n){if(!in.read(static_cast<char*>(dst),n)) throw std::runtime_error("Truncated trace");};
        char magic[8];read(magic,8);
        if(std::string(magic,8)!="HSPTRC01") throw std::runtime_error("Wrong trace schema");
        read(&io_size,4);read(&slots,4);read(&data_bytes,8);read(&record_count,4);read(&seed,4);
        if(io_size!=4096 || slots!=65536 || record_count>100000 || data_bytes%4096) throw std::runtime_error("Invalid trace header");
        records.reserve(record_count);
        for(uint32_t k=0;k<record_count;++k) {
            Record r;read(&r.batch,4);read(&r.ppm,4);read(&r.count,4);read(&r.phase,4);read(&r.round,4);
            if(!r.count || r.count>slots || r.phase>3) throw std::runtime_error("Invalid trace record");
            r.entries.resize(r.count);read(r.entries.data(),r.count*sizeof(Entry));
            std::vector<bool> used(slots,false);
            for(auto e:r.entries) {
                if(uint64_t(e.block)*4096>=data_bytes || e.slot>=slots || used[e.slot]) throw std::runtime_error("Out-of-range/overlapping destination");
                used[e.slot]=true;
            }
            records.push_back(std::move(r));
        }
        if(in.peek()!=std::char_traits<char>::eof()) throw std::runtime_error("Trailing trace data");
    }
};
struct DeviceBuffer {
    void* raw=nullptr;
    void* data=nullptr;
    size_t bytes;
    std::vector<uint64_t> verification_buffer;
    explicit DeviceBuffer(size_t size):bytes(size) {
        cuda_check(cudaMalloc(&raw,size+65536),"allocate HBM");
        data=reinterpret_cast<void*>((reinterpret_cast<uintptr_t>(raw)+65535)&~uintptr_t(65535));
    }
    ~DeviceBuffer(){if(raw)cudaFree(raw);}
    void poison(){
        cuda_check(cudaMemset(data,0xa5,bytes),"poison HBM");
        // cudaMemset is asynchronous to the host. cuFile batch submission is
        // not ordered on this CUDA stream, so finish poisoning before DMA.
        cuda_check(cudaDeviceSynchronize(),"finish poison before external DMA");
    }
    bool verify(const Record& r) {
        if(verification_buffer.empty())verification_buffer.resize(bytes/8);
        auto& host=verification_buffer;
        cuda_check(cudaMemcpy(host.data(),data,bytes,cudaMemcpyDeviceToHost),"verify D2H");
        for(auto e:r.entries) for(uint64_t word=0;word<512;++word) {
            const auto expected=(uint64_t(e.block)<<32)^0xD6E8FEB86659FD93ULL^(word*0x9E3779B97F4A7C15ULL);
            if(host[size_t(e.slot)*512+word]!=expected) {
                std::cerr<<"Mismatch block="<<e.block<<" slot="<<e.slot<<" word="<<word
                         <<" expected="<<expected<<" observed="<<host[size_t(e.slot)*512+word]<<std::endl;
                return false;
            }
        }
        return true;
    }
};
struct Timing {double submit_us=0,completion_us=0;};
constexpr unsigned queue_depth=256;
constexpr unsigned group_size=16;
constexpr unsigned windows=queue_depth/group_size;
