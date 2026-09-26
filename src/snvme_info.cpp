// Read-only public UAPI handshake; no queue allocation or GPU execution.
#include <uapi/tutti_snvme.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdio>
#include <cstring>
#include <cerrno>
int main(int argc,char**argv){
 if(argc!=2)return 2;
 int fd=open(argv[1],O_RDONLY);if(fd<0){std::perror("open chrdev");return 1;}
 nvm_ioctl_dev info{};int rc=ioctl(fd,NVM_GET_DEV_INFO,&info);int e=errno;close(fd);
 if(rc){std::fprintf(stderr,"GET_DEV_INFO: %s\n",std::strerror(e));return 1;}
 info.disk_name[sizeof(info.disk_name)-1]=0;
 std::printf("{\"abi_version\":%u,\"expected_abi\":%u,\"capabilities\":%u,\"disk_name\":\"%s\",\"block_size\":%llu,\"queue_depth\":%u,\"bar0_size\":%u}\n",
 info.abi_version,TUTTI_SNVME_ABI_VERSION,info.capabilities,info.disk_name,(unsigned long long)info.block_size,info.q_depth,info.bar0_size);
 return info.abi_version==TUTTI_SNVME_ABI_VERSION?0:1;
}
