#include <fcntl.h>
#include <linux/spi/spidev.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <unistd.h>
struct endpoint { int number, mode; unsigned hz; int passed; };
static pthread_barrier_t barrier;
static char result[256] __attribute__((aligned(4096)));
static void *check(void *arg) {
    struct endpoint *e=arg;
    char path[64];
    snprintf(path,sizeof(path),"/dev/spidev%d.0",e->number);
    int fd=open(path,O_RDWR);
    pthread_barrier_wait(&barrier);
    if(fd<0) return NULL;
    for(unsigned i=0;i<64;i++) {
        uint8_t tx[8]={0,0,0,0,0,0,i,e->number},rx[8]={0};
        struct spi_ioc_transfer t={.tx_buf=(uintptr_t)tx,.rx_buf=(uintptr_t)rx,.len=sizeof(tx)};
        if(ioctl(fd,SPI_IOC_MESSAGE(1),&t)!=8 || rx[0]!=e->number || rx[1]!=e->mode ||
           ((uint32_t)rx[2]<<24 | (uint32_t)rx[3]<<16 | rx[4]<<8 | rx[5])!=e->hz ||
           rx[6]!=i || rx[7]!=e->number) break;
        e->passed++;
    }
    close(fd); return NULL;
}
int main(void) {
    struct endpoint a={.number=2,.mode=2,.hz=1000000}, b={.number=3,.mode=3,.hz=8000000};
    char nonce[80]="missing";
    FILE *f=fopen("/nonce","r");
    if(f) {if (fscanf(f,"%79s",nonce)!=1) strcpy(nonce,"missing"); fclose(f);}
    mount("dev","/dev","devtmpfs",0,NULL);
    int m=open("/qa_spi.ko",O_RDONLY);
    if(m>=0 && syscall(SYS_finit_module,m,"",0)==0) {
        pthread_t one,two;
        pthread_barrier_init(&barrier,NULL,2);
        if(!pthread_create(&one,NULL,check,&a) && !pthread_create(&two,NULL,check,&b)) {
            pthread_join(one,NULL);pthread_join(two,NULL);
        }
    }
    snprintf(result,sizeof(result),"SPI-proof/%s/%d/%d/end",nonce,a.passed,b.passed);
    __asm__ volatile("" : : "r"(result) : "memory");
    reboot(RB_POWER_OFF);pause();return 0;
}
