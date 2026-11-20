// SPDX-License-Identifier: GPL-3.0-or-later
#include "hal.hpp"
#include "radio_lock.hpp"
#include <iostream>

static std::map<int,int> fds, levels;
static int failPin=-1, edges=0;
extern "C" {
int wiringPiH618LineABI() { return 1; }
int wiringPiH618HeaderToNative(int) { return 76; }
int wiringPiH618LineRequest(int pin,int dir,int initial,int,int,uint32_t) {
    if(pin==failPin) return -1;
    lw::require(!fds.count(pin) && (dir==WPI_H618_OUTPUT)==(pin==12 || pin==31),"Duplicate or incorrect request");
    levels[pin]=initial;
    return fds[pin]=open("/dev/null",O_RDONLY|O_CLOEXEC);
}
int wiringPiH618LineWrite(int fd,int level) {
    for(auto [pin,desc]:fds) if(fd==desc && pin!=failPin) { levels[pin]=level; return 0; }
    return -1;
}
int wiringPiH618LineRead(int fd) {
    for(auto [pin,desc]:fds) if(fd==desc && pin!=failPin) return levels[pin];
    return -1;
}
}
static void edge() { ++edges; }
template<class F> void rejects(F fn) {
    try { fn(); } catch(const std::exception&) { return; }
    throw std::runtime_error("Expected rejection");
}
int main(int argc, char** argv) {
    try {
        if(argc==3 && std::string(argv[1])=="qemu-spi") {
            const lw::fs::path dev(argv[2]);
            auto endpoint = lw::fs::path("/sys/class/spidev")/dev.filename()/"device/of_node";
            lw::require(dev.parent_path()=="/dev" && lw::fs::equivalent(endpoint,"/proc/device-tree/sx1262-spi-test/radio@0"),
                        "Expected the QEMU SPI fixture");
            lw::Fd fd(open(dev.c_str(),O_RDWR|O_CLOEXEC|O_NOFOLLOW));
            lw::configureSpi(fd.n);
            uint8_t command[]={0xc0,0}, response[2]={};
            lw::transferSpi(fd.n,command,sizeof(command),response);
            lw::require(response[0]==response[1],"Inconsistent virtual MISO");
            std::cout<<unsigned(response[0])<<"\n"; return 0;
        }
        if(argc==3 && std::string(argv[1])=="lock") {
            lw::RadioLock lock(argv[2]);
            std::cout<<"locked"<<std::endl;
            std::cin.get(); return 0;
        }
        if(argc==3 && std::string(argv[1])=="discover") {
            std::cout<<lw::discoverSpi(argv[2]).string()<<"\n"; return 0;
        }
        if(argc==4 && std::string(argv[1])=="route") {
            lw::validateRoute(argv[2],argv[3]); return 0;
        }
        {
            lw::Hal hal("/no-such-device");
            Module module(&hal,RADIOLIB_NC,36,12,38);
            hal.pinMode(RADIOLIB_NC,OUTPUT); hal.digitalWrite(RADIOLIB_NC,LOW);
            rejects([&]{hal.pinMode(40,OUTPUT);});
            rejects([&]{hal.pinMode(38,OUTPUT);});
            lw::configureSwitch(module);
            for(auto [mode,value]:{std::pair{Module::MODE_RX,1}, {Module::MODE_TX,0}, {Module::MODE_IDLE,0}}) {
                module.setRfSwitchState(mode);
                lw::require(levels.at(31)==value,"RF switch polarity");
            }
            failPin=12; rejects([&]{hal.pinMode(12,OUTPUT);}); failPin=-1;
            hal.pinMode(12,OUTPUT); lw::require(levels.at(12)==1,"RESET must start deasserted");
            hal.pinMode(38,INPUT); failPin=38; rejects([&]{hal.digitalRead(38);}); failPin=-1;
            failPin=31; rejects([&]{hal.digitalWrite(31,0);}); failPin=-1;
            hal.attachInterrupt(36,edge,INT_EDGE_RISING);
            levels[36]=1; hal.yield(); hal.yield(); levels[36]=0; hal.yield(); levels[36]=1; hal.yield();
            lw::require(edges==2,"DIO1 edge dispatch");
            hal.detachInterrupt(36); lw::stopping=1; rejects([&]{hal.yield();}); lw::stopping=0;
            rejects([&]{hal.spiBegin();});
        }
        for(auto [pin,fd]:fds) lw::require(fcntl(fd,F_GETFD)==-1 && errno==EBADF,"Leaked GPIO");
    } catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
}
