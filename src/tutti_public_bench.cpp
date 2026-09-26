// Public API only: xPU-IO/Tutti v0.1.1, commit 38c8a68ab99c47a9a31f120b1018b6a7e01734d1.
// Basis: tutti/include/tutti/presets/local_nvme.h and examples/layerwise_kv_overlap.
#include "bench_common.h"
#include <tutti/presets/local_nvme.h>
#include <uapi/tutti_snvme.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <filesystem>
#include <sys/stat.h>
#include <iomanip>
#include <memory>
#include <optional>

void check_status(const tutti::Status& s, const char* where) {
    if (!s.ok()) throw std::runtime_error(std::string(where)+": "+s.message());
}
struct PublicBackend {
    struct Window { cudaStream_t stream=nullptr; std::optional<tutti::IoHandle> io; unsigned n=0; };
    std::array<Window,windows> slots{};
    tutti::presets::RuntimeWithTelemetry bundle;
    tutti::MemoryHandle memory;
    tutti::TargetHandle file;
    void initialize(DeviceBuffer& buffer, const Workload& work, const std::string& path,
                    const std::string& chrdev, const std::string& bdf, const std::string& block) {
        struct stat f{},d{};
        if (stat(path.c_str(),&f) || stat(block.c_str(),&d) || !S_ISREG(f.st_mode) || !S_ISBLK(d.st_mode)
            || f.st_dev!=d.st_rdev || uint64_t(f.st_size)!=work.data_bytes)
            throw std::runtime_error("File size/backing device mismatch");
        int fd=open(chrdev.c_str(),O_RDONLY);
        if(fd<0)throw std::runtime_error("Cannot open snvme character device");
        nvm_ioctl_dev info{};int info_rc=ioctl(fd,NVM_GET_DEV_INFO,&info);::close(fd);
        info.disk_name[sizeof(info.disk_name)-1]=0;
        if(info_rc || info.abi_version!=TUTTI_SNVME_ABI_VERSION || info.block_size!=4096
            || std::filesystem::path(block).filename().string()!=info.disk_name)
            throw std::runtime_error("Public UAPI ABI/block identity mismatch; no GPU IO submitted");
        std::ifstream resources("/sys/bus/pci/devices/"+bdf+"/resource");
        uint64_t start=0,end=0,flags=0;
        if (!(resources>>std::hex>>start>>end>>flags) || end<start) throw std::runtime_error("Cannot read BAR0 geometry");
        auto sysblock=std::filesystem::canonical("/sys/class/block/"+std::filesystem::path(block).filename().string()+"/device").string();
        if (sysblock.find("/"+bdf+"/")==std::string::npos) throw std::runtime_error("Block BDF mismatch");
        tutti::presets::LocalNvmePreset cfg;
        cfg.device.ssnvme_path=chrdev; cfg.device.pci_bdf=bdf;
        cfg.device.backing_device=block; cfg.device.mount_path=std::filesystem::path(path).parent_path();
        cfg.device.bar0_size=end-start+1;
        cfg.gpu_id=0; cfg.num_queues=16; cfg.max_batch_entries=16; cfg.max_in_flight_operations=16;
        cfg.handle_cache_capacity=0; cfg.prp_cache_capacity=0;
        bundle=tutti::presets::make_local_nvme_runtime(cfg);
        if(!bundle.runtime) throw std::runtime_error("Public LocalNvmePreset initialization failed");
        auto opened=bundle.runtime->open("file://"+path,{});
        if(!opened.ok()) throw std::runtime_error("Public open: "+opened.status().message());
        file=opened.value();
        auto reg=bundle.runtime->register_memory({buffer.data,buffer.bytes,tutti::MemoryKind::DEVICE,
            tutti::MemoryOwnership::CALLER_OWNED,0,"CUDA",4096});
        if(!reg.ok()) throw std::runtime_error("Public registration: "+reg.status().message());
        memory=reg.value();
        for(auto& w:slots) cuda_check(cudaStreamCreateWithFlags(&w.stream,cudaStreamNonBlocking),"create stream");
        cuda_check(cudaDeviceSynchronize(),"initialize");
        std::cout<<"Tutti-v0.1.1 public_api BDF="<<bdf<<" block="<<block<<" chrdev="<<chrdev
                 <<" BAR0="<<cfg.device.bar0_size<<" queues=16 window=16 inflight_cap=256"<<std::endl;
    }
    Timing run(const Record& r) {
        std::vector<tutti::IoRequest> prepared;
        prepared.reserve(r.count);
        for(auto e:r.entries) prepared.push_back({tutti::IoDirection::READ,memory,uint64_t(e.slot)*4096,file,uint64_t(e.block)*4096,4096});
        unsigned next=0,done=0;Timing timing;
        auto begin=Clock::now();
        auto submit=[&](Window& w) {
            unsigned n=std::min(group_size,r.count-next);
            auto a=Clock::now();
            auto out=bundle.runtime->submit(prepared.data()+next,n,{tutti::ExecutionDomain::DEVICE_EXECUTION,0,w.stream});
            timing.submit_us+=micros(a,Clock::now());
            check_status(out.status,"public submit");
            if(!out.io || out.initial_states.size()!=n) throw std::runtime_error("Missing public IO handle/states");
            for(auto& state:out.initial_states) {
                check_status(state.status,"request status");
                if(state.state!=tutti::IoRequestState::ACCEPTED) throw std::runtime_error("Partial submit rejected");
            }
            w.io=out.io; w.n=n; next+=n;
        };
        for(auto& w:slots) if(next<r.count) submit(w);
        while(done<r.count) {
            for(auto& w:slots) {
                if(!w.io)continue;
                auto snapshot=bundle.runtime->query(*w.io);
                if(!snapshot.ok())throw std::runtime_error(snapshot.status().message());
                if(snapshot.value().state==tutti::IoState::IN_FLIGHT)continue;
                auto result=bundle.runtime->wait(*w.io,0);
                check_status(result.observation_status,"observe public completion");
                if(!result.result || result.result->state!=tutti::IoState::COMPLETED)throw std::runtime_error("Public IO failed");
                check_status(result.result->status,"public IO result");
                check_status(bundle.runtime->release_io(*w.io),"release public IO");
                done+=w.n;w.io.reset();
                if(next<r.count)submit(w);
            }
            if(Clock::now()-begin>std::chrono::seconds(30))throw std::runtime_error("Public IO round timeout");
        }
        timing.completion_us=micros(begin,Clock::now());
        return timing;
    }
    void close() {
        check_status(bundle.runtime->unregister_memory(memory),"unregister public memory");
        check_status(bundle.runtime->close(file),"close public file");
        check_status(bundle.runtime->shutdown(10000),"shutdown public runtime");
        for(auto& w:slots)cuda_check(cudaStreamDestroy(w.stream),"destroy stream");
    }
};
int main(int argc,char** argv) {
    std::unique_ptr<DeviceBuffer> buffer;
    std::unique_ptr<PublicBackend> backend;
    try {
        if(argc!=7)throw std::runtime_error("usage: tutti_public_bench DATA TRACE OUTPUT.csv CHRDEV BDF BLOCKDEV");
        if(!getenv("CUDA_VISIBLE_DEVICES"))throw std::runtime_error("Use a GPU reservation");
        if(std::filesystem::exists(argv[3]))throw std::runtime_error("Refusing existing CSV");
        Workload work(argv[2]);cuda_check(cudaSetDevice(0),"select GPU");
        char pci[32]{};cuda_check(cudaDeviceGetPCIBusId(pci,sizeof pci,0),"GPU identity");
        std::cout<<"GPU="<<pci<<" upstream_commit=38c8a68ab99c47a9a31f120b1018b6a7e01734d1"<<std::endl;
        buffer=std::make_unique<DeviceBuffer>(uint64_t(work.slots)*4096);
        backend=std::make_unique<PublicBackend>();
        backend->initialize(*buffer,work,argv[1],argv[4],argv[5],argv[6]);
        // Public Runtime may register with the DataPath lazily on first submit.
        // Prime once outside recorded rounds to exclude deferred registration cost.
        // GDS performs its registration eagerly during initialize().
        buffer->poison();backend->run(work.records.front());
        if(!buffer->verify(work.records.front()))throw std::runtime_error("Priming verification failed");
        backend->bundle.telemetry.reset_counters();
        std::ofstream out(argv[3]);out<<std::setprecision(12);
        out<<"backend,request_batch,miss_rate,n_reads,io_size,queue_depth,round,submit_us,completion_us,bytes_read,correct,direct_path,error,phase,submission_group\n";
        uint64_t expected_submits=0;
        for(auto& r:work.records) {
            buffer->poison();auto t=backend->run(r);bool good=buffer->verify(r);
            expected_submits+=(r.count+group_size-1)/group_size;
            out<<"Tutti-v0.1.1,"<<r.batch<<','<<double(r.ppm)/1e6<<','<<r.count<<",4096,256,"<<r.round<<','<<t.submit_us<<','<<t.completion_us<<','<<uint64_t(r.count)*4096<<','<<(good?"true":"false")<<",public_local_nvme_gpu,"<<(good?"":"data_mismatch")<<','<<r.phase<<",16\n";
            if(r.phase>=2 || !good){out.flush();std::cout<<"phase="<<r.phase<<" n_reads="<<r.count<<" "<<(good?"PASS":"FAIL")<<std::endl;}
            if(!good)throw std::runtime_error("Data mismatch");
        }
        out.flush();if(!out)throw std::runtime_error("CSV write failed");
        auto submits=backend->bundle.telemetry.submit_call_count(), launches=backend->bundle.telemetry.kernel_launch_count();
        std::cout<<"PUBLIC_PATH submits="<<submits<<" kernel_launches="<<launches<<" expected="<<expected_submits<<std::endl;
        if(submits!=expected_submits || launches!=expected_submits)throw std::runtime_error("Unexpected kernel launch path");
        backend->close();return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<std::endl;std::_Exit(1);}
}
