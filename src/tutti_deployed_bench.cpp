// Thin adapter over the *deployed Tutti* queue/memory helpers and its unmodified
// launch_pool_file_xfer kernel. Source/binary hashes: third_party/Tutti-deployed/PROVENANCE.json.
// No Coordinator/HostFsBackedNvmeStorage bootstrap, filesystem writes, mkfs,
// metadata reconciliation, raw writes, daemon bring-up or device binding.
#include "bench_common.h"
#include "nvmeservice_backed_registry.h"
#include "nvme_queue_group.h"
#include "host_device_memory_subsystem.h"
#include "nvme_file_device_handle.h"
#include "fiemap_helper.h"
#include "local_nvme/launch_pool_file.h"
#include "local_nvme/pool_file.h"
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <filesystem>
#include <iomanip>
#include <memory>

struct TuttiBackend {
    struct Window {
        cudaStream_t stream=nullptr;
        tutti::PoolNvmeEntry* device_entries=nullptr;
        std::array<tutti::PoolNvmeEntry,group_size> host_entries{};
        unsigned pending=0;
    };
    std::array<Window,windows> slots;
    std::unique_ptr<tutti::NvmeServiceBackedRegistry> registry;
    std::unique_ptr<tutti::HostDeviceMemorySubsystem> memory;
    tutti::MemoryRegion* region=nullptr;
    tutti::NvmeFileDeviceHandle* device_handle=nullptr;
    tutti::LbaExtent* overflow=nullptr;
    std::vector<const tutti::AddressDescriptor*> descriptors;
    DeviceBuffer& buffer;
    int fd=-1;
    explicit TuttiBackend(DeviceBuffer& b):buffer(b){}
    void initialize(const std::string& path,uint64_t expected_size,int device_id,const std::string& expected_bdf,const std::string& endpoint) {
        fd=open(path.c_str(),O_RDONLY|O_DIRECT);
        if(fd<0)throw std::runtime_error("open data failed");
        struct stat file_stat{};
        if(fstat(fd,&file_stat) || uint64_t(file_stat.st_size)!=expected_size)throw std::runtime_error("Data size mismatch");
        tutti::NvmeServiceBackedRequest request;
        request.daemon_device_id=device_id;request.cuda_device=0;request.daemon_accel_id=0;
        request.num_queues=16;request.build_queue_group=true;request.num_user_queues=16;
        registry=std::make_unique<tutti::NvmeServiceBackedRegistry>(endpoint,std::vector<tutti::NvmeServiceBackedRequest>{request});
        if(!registry->Open() || registry->device_count()!=1)throw std::runtime_error("Tutti client queue acquisition failed");
        auto dev=registry->device_at(0);
        auto local=static_cast<tutti::LocalNvmeDevice*>(dev->backend_private);
        if(!local || !local->queue_group || local->pci_addr!=expected_bdf)throw std::runtime_error("Wrong controller BDF or absent queue group");
        struct stat block_stat{};
        if(stat(local->block_path.c_str(),&block_stat) || file_stat.st_dev!=block_stat.st_rdev)
            throw std::runtime_error("File device differs from leased NVMe device; refusing raw reads");
        if(local->blk_size!=4096 || local->queue_group->n_qps()!=16)throw std::runtime_error("Unsupported block/queue geometry");
        std::cout<<"Tutti-deployed BDF="<<local->pci_addr<<" device="<<local->block_path
                 <<" NVMe_queues="<<local->queue_group->n_qps()<<" queue_entries="<<local->queue_depth<<std::endl;
        // Use deployed Tutti's extent reader on the already-written file.
        auto mapped=tutti::read_extents(fd,local->blk_size);
        if(!mapped.ok)throw std::runtime_error("Tutti FIEMAP: "+mapped.error);
        uint64_t covered=0;for(auto e:mapped.extents)covered+=e.length_blocks*4096;
        if(covered!=expected_size)throw std::runtime_error("Extent coverage differs from file size");
        tutti::NvmeFileDeviceHandle handle{};
        handle.file_id=1;handle.logical_size_bytes=expected_size;handle.header_bytes=0;
        handle.nvme_block_size=local->blk_size;handle.nvme_block_size_log=local->blk_size_log;
        handle.namespace_id=local->namespace_id;handle.num_extents=mapped.extents.size();
        handle.d_qps=local->queue_group->d_qps();handle.num_d_qps=local->queue_group->n_qps();
        unsigned first=std::min<size_t>(mapped.extents.size(),tutti::kNvmeFileDeviceHandleInlineExtents);
        std::copy_n(mapped.extents.data(),first,handle.extents);
        if(mapped.extents.size()>first) {
            size_t bytes=(mapped.extents.size()-first)*sizeof(tutti::LbaExtent);
            cuda_check(cudaMalloc(reinterpret_cast<void**>(&overflow),bytes),"allocate extent overflow");
            cuda_check(cudaMemcpy(overflow,mapped.extents.data()+first,bytes,cudaMemcpyHostToDevice),"upload extent overflow");
            handle.extents_overflow=overflow;
        }
        cuda_check(cudaMalloc(reinterpret_cast<void**>(&device_handle),sizeof(handle)),"allocate file handle");
        cuda_check(cudaMemcpy(device_handle,&handle,sizeof(handle),cudaMemcpyHostToDevice),"upload file handle");
        memory=std::make_unique<tutti::HostDeviceMemorySubsystem>();
        memory->set_descriptor_format(tutti::DescriptorFormat::PRP);
        memory->bind_devices(registry->list());
        region=memory->register_tensor({buffer.data,buffer.bytes,{},4096});
        if(!region)throw std::runtime_error(std::string("Tutti register_tensor: ")+(memory->last_register_error()?memory->last_register_error():"unknown"));
        descriptors.resize(buffer.bytes/4096);
        for(size_t i=0;i<descriptors.size();++i) {
            auto view=memory->lookup_io_slice(region,reinterpret_cast<uint64_t>(buffer.data)+i*4096);
            if(!view || view->num_ios!=1 || view->total_bytes!=4096)throw std::runtime_error("Unexpected PRP slice");
            descriptors[i]=view->d_ios;
        }
        cuda_check(tutti::prepare_pool_file_kernels(),"prepare Tutti kernels");
        for(auto& w:slots) {
            cuda_check(cudaStreamCreateWithFlags(&w.stream,cudaStreamNonBlocking),"create stream");
            cuda_check(cudaMalloc(reinterpret_cast<void**>(&w.device_entries),group_size*sizeof(tutti::PoolNvmeEntry)),"allocate queue descriptors");
        }
        cuda_check(cudaDeviceSynchronize(),"finish Tutti initialization");
    }
    ~TuttiBackend() {
        for(auto& w:slots) {if(w.stream)cudaStreamDestroy(w.stream);if(w.device_entries)cudaFree(w.device_entries);}
        if(region)memory->unregister(region);
        memory.reset();
        if(device_handle)cudaFree(device_handle);
        if(overflow)cudaFree(overflow);
        registry.reset();
        if(fd>=0)close(fd);
    }
    Timing run(const Record& r) {
        std::vector<tutti::PoolNvmeEntry> prepared(r.count);
        for(unsigned i=0;i<r.count;++i)
            prepared[i]={device_handle,descriptors[r.entries[i].slot],uint64_t(r.entries[i].block)*4096,4096,0};
        unsigned next=0,completed=0;Timing timing;
        auto begin=Clock::now();
        auto submit=[&](Window& w) {
            unsigned n=std::min(group_size,r.count-next);
            std::copy_n(prepared.data()+next,n,w.host_entries.data());
            auto a=Clock::now();
            cuda_check(cudaMemcpyAsync(w.device_entries,w.host_entries.data(),n*sizeof(tutti::PoolNvmeEntry),cudaMemcpyHostToDevice,w.stream),"submit descriptors");
            cuda_check(tutti::launch_pool_file_xfer(w.stream,w.device_entries,n,true,32),"launch Tutti GPU IO");
            timing.submit_us+=micros(a,Clock::now());w.pending=n;next+=n;
        };
        for(auto& w:slots)if(next<r.count)submit(w);
        while(completed<r.count) {
            for(auto& w:slots) {
                if(!w.pending)continue;
                auto status=cudaStreamQuery(w.stream);
                if(status==cudaErrorNotReady)continue;
                cuda_check(status,"Tutti completion");
                completed+=w.pending;w.pending=0;
                if(next<r.count)submit(w);
            }
            if(Clock::now()-begin>std::chrono::seconds(30))throw std::runtime_error("Tutti batch exceeded 30 seconds");
        }
        timing.completion_us=micros(begin,Clock::now());return timing;
    }
};

int main(int argc,char** argv) {
    std::unique_ptr<DeviceBuffer> buffer;
    std::unique_ptr<TuttiBackend> backend;
    try {
        if(argc!=6 && argc!=7)throw std::runtime_error("usage: tutti_deployed_bench DATA TRACE OUTPUT.csv DAEMON_DEVICE_ID EXPECTED_BDF [ENDPOINT]");
        if(!getenv("CUDA_VISIBLE_DEVICES"))throw std::runtime_error("Use canhazgpu run");
        if(std::filesystem::exists(argv[3]))throw std::runtime_error("Refusing existing output");
        Workload work(argv[2]);cuda_check(cudaSetDevice(0),"cudaSetDevice");
        buffer=std::make_unique<DeviceBuffer>(uint64_t(work.slots)*4096);
        backend=std::make_unique<TuttiBackend>(*buffer);
        backend->initialize(argv[1],work.data_bytes,std::stoi(argv[4]),argv[5],argc==7?argv[6]:"127.0.0.1:50051");
        std::ofstream out(argv[3]);out<<std::setprecision(12);
        out<<"backend,request_batch,miss_rate,n_reads,io_size,queue_depth,round,submit_us,completion_us,bytes_read,correct,direct_path,error,phase,submission_group\n";
        for(auto& r:work.records) {
            buffer->poison();auto t=backend->run(r);bool correct=buffer->verify(r);
            out<<"Tutti-deployed,"<<r.batch<<','<<double(r.ppm)/1e6<<','<<r.count<<",4096,256,"<<r.round<<','<<t.submit_us<<','<<t.completion_us<<','<<uint64_t(r.count)*4096<<','<<(correct?"true":"false")<<",gpu_nvme_kernel,"<<(correct?"":"data_mismatch")<<','<<r.phase<<",16\n";
            if(r.phase>=2 || !correct) {
                out.flush();std::cout<<"phase="<<r.phase<<" n_reads="<<r.count<<" "<<(correct?"PASS":"FAIL")<<std::endl;
            }
            if(!correct)throw std::runtime_error("Data verification failure");
        }
        out.flush();if(!out)throw std::runtime_error("CSV write failed");
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<std::endl;std::_Exit(1);}
}
