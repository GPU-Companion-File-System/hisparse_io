// Official batch API: https://docs.nvidia.com/gpudirect-storage/api-reference-guide/index.html#cufilebatchiosubmit
#include "bench_common.h"
#include <cufile.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <filesystem>
#include <iostream>
#include <iomanip>
#include <cstring>
#include <memory>

void gds_check(CUfileError_t e,const char* stage) {
    if(e.err!=CU_FILE_SUCCESS) throw std::runtime_error(std::string(stage)+": "+CUFILE_ERRSTR(e.err));
}
struct GdsBackend {
    struct Window {
        CUfileBatchHandle_t handle=nullptr;
        unsigned remaining=0;
        std::array<CUfileIOParams_t,group_size> params{};
        std::array<CUfileIOEvents_t,group_size> events{};
    };
    std::array<Window,windows> slots;
    int fd=-1;
    bool driver=false;
    unsigned registered_segments=0;
    static constexpr size_t segment_bytes=1<<20;
    CUfileHandle_t file=nullptr;
    DeviceBuffer& buffer;
    explicit GdsBackend(DeviceBuffer& b):buffer(b){}
    void initialize(const std::string& path,uint64_t expected_size) {
        fd=open(path.c_str(),O_RDONLY|O_DIRECT);
        if(fd<0)throw std::runtime_error("open data: "+std::string(strerror(errno)));
        struct stat st{};
        if(fstat(fd,&st) || uint64_t(st.st_size)!=expected_size)throw std::runtime_error("Data size mismatch");
        gds_check(cuFileDriverOpen(),"cuFileDriverOpen");driver=true;
        CUfileDescr_t desc{};desc.type=CU_FILE_HANDLE_TYPE_OPAQUE_FD;desc.handle.fd=fd;
        gds_check(cuFileHandleRegister(&file,&desc),"cuFileHandleRegister");
        // GDS 1.13.1 batch validation constrains size + devPtr_offset to the
        // 1 MiB IO limit. Register aligned 1 MiB views of the same HBM buffer
        // so every offset stays in that range without moving destinations.
        for(size_t offset=0;offset<buffer.bytes;offset+=segment_bytes) {
            gds_check(cuFileBufRegister(static_cast<char*>(buffer.data)+offset,segment_bytes,0),"cuFileBufRegister");
            ++registered_segments;
        }
        for(auto& w:slots)gds_check(cuFileBatchIOSetUp(&w.handle,group_size),"cuFileBatchIOSetUp");
    }
    ~GdsBackend() {
        for(auto& w:slots)if(w.handle)cuFileBatchIODestroy(w.handle);
        for(unsigned i=0;i<registered_segments;++i)cuFileBufDeregister(static_cast<char*>(buffer.data)+i*segment_bytes);
        if(file)cuFileHandleDeregister(file);
        if(driver)cuFileDriverClose();
        if(fd>=0)close(fd);
    }
    Timing run(const Record& r) {
        // Descriptor preparation is outside timing, as for both backends.
        std::vector<CUfileIOParams_t> prepared(r.count);
        for(unsigned i=0;i<r.count;++i) {
            auto& p=prepared[i];p.mode=CUFILE_BATCH;p.fh=file;p.opcode=CUFILE_READ;
            const uint64_t offset=uint64_t(r.entries[i].slot)*4096;
            p.u.batch.devPtr_base=static_cast<char*>(buffer.data)+(offset/segment_bytes)*segment_bytes;
            p.u.batch.devPtr_offset=offset%segment_bytes;
            p.u.batch.file_offset=uint64_t(r.entries[i].block)*4096;p.u.batch.size=4096;
            p.cookie=reinterpret_cast<void*>(uintptr_t(i+1));
        }
        unsigned next=0,completed=0;
        Timing timing;
        auto begin=Clock::now();
        auto submit=[&](Window& w) {
            const unsigned n=std::min(group_size,r.count-next);
            // API input storage remains valid until that window completes.
            std::copy_n(prepared.data()+next,n,w.params.data());
            const auto a=Clock::now();
            auto e=cuFileBatchIOSubmit(w.handle,n,w.params.data(),0);
            const auto b=Clock::now();timing.submit_us+=micros(a,b);
            gds_check(e,"cuFileBatchIOSubmit");w.remaining=n;next+=n;
        };
        for(auto& w:slots)if(next<r.count)submit(w);
        while(completed<r.count) {
            for(auto& w:slots) {
                if(!w.remaining)continue;
                unsigned n=group_size;
                timespec timeout{0,0};
                gds_check(cuFileBatchIOGetStatus(w.handle,0,&n,w.events.data(),&timeout),"cuFileBatchIOGetStatus");
                if(n>w.remaining)throw std::runtime_error("Extra completion");
                for(unsigned j=0;j<n;++j) {
                    if(w.events[j].status!=CUFILE_COMPLETE || w.events[j].ret!=4096)
                        throw std::runtime_error("IO error status="+std::to_string(w.events[j].status)+" ret="+std::to_string(static_cast<ssize_t>(w.events[j].ret)));
                }
                w.remaining-=n;completed+=n;
                if(!w.remaining && next<r.count)submit(w);
            }
            if(Clock::now()-begin>std::chrono::seconds(30))throw std::runtime_error("Batch exceeded 30 seconds");
        }
        timing.completion_us=micros(begin,Clock::now());
        return timing;
    }
};

int main(int argc,char** argv) {
    // Keep async-resource owners outside the try scope: failure exits before
    // their destructors can free memory still referenced by an outstanding IO.
    std::unique_ptr<DeviceBuffer> buffer;
    std::unique_ptr<GdsBackend> backend;
    try {
        if(argc!=4)throw std::runtime_error("usage: gds_bench DATA TRACE OUTPUT.csv");
        if(!getenv("CUDA_VISIBLE_DEVICES"))throw std::runtime_error("Use canhazgpu run");
        if(std::filesystem::exists(argv[3]))throw std::runtime_error("Refusing existing output");
        Workload work(argv[2]);
        cuda_check(cudaSetDevice(0),"cudaSetDevice");
        char pci[32]{};cuda_check(cudaDeviceGetPCIBusId(pci,sizeof pci,0),"GPU PCI identity");
        std::cout<<"GPU="<<pci<<" trace_records="<<work.record_count<<" HBM="<<uint64_t(work.slots)*4096<<std::endl;
        buffer=std::make_unique<DeviceBuffer>(uint64_t(work.slots)*4096);
        backend=std::make_unique<GdsBackend>(*buffer);backend->initialize(argv[1],work.data_bytes);
        std::ofstream out(argv[3]);out<<std::setprecision(12);
        out<<"backend,request_batch,miss_rate,n_reads,io_size,queue_depth,round,submit_us,completion_us,bytes_read,correct,direct_path,error,phase,submission_group\n";
        for(const auto& r:work.records) {
            bool boundary=(r.phase==2 || r.phase==3);
            buffer->poison();
            const auto t=backend->run(r);
            bool correct=buffer->verify(r);
            out<<"GDS,"<<r.batch<<','<<double(r.ppm)/1e6<<','<<r.count<<",4096,256,"<<r.round<<','
               <<t.submit_us<<','<<t.completion_us<<','<<uint64_t(r.count)*4096<<','
               <<(correct?"true":"false")<<",pending_log_review,"<<(correct?"":"data_mismatch")<<','<<r.phase<<",16\n";
            if(boundary || !correct) {
                out.flush();std::cout<<"check "<<(r.phase==2?"before":"after")<<" n_reads="<<r.count<<" "<<(correct?"PASS":"FAIL")<<std::endl;
                if(!correct)throw std::runtime_error("Data verification failure");
            }
        }
        out.flush();if(!out)throw std::runtime_error("CSV write failed");
        std::cout<<"GDS matrix complete; audit direct-path logs before comparison"<<std::endl;
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"FAIL: "<<e.what()<<std::endl;
        // Failures may leave asynchronous DMA active. Do not destruct/free GPU
        // buffers while requests might reference them; process teardown owns it.
        std::_Exit(1);
    }
}
