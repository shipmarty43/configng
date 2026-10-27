// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <RadioLib.h>
#include <wiringPi.h>
#include <linux/spi/spidev.h>
#include <sys/ioctl.h>
#include <chrono>
#include <csignal>
#include <fstream>
#include <set>
#include <thread>

namespace lw {
inline volatile sig_atomic_t stopping = 0;
// Physical header numbering. The Waveshare profile is deliberately fixed in v1.
class Hal : public RadioLibHal {
    std::string path;
    int spi = -1;
    std::set<unsigned> owned;
    void (*callback)() = nullptr;
    bool previous = false;
    bool initialized = false;
    std::chrono::steady_clock::time_point epoch = std::chrono::steady_clock::now();
    void pin(unsigned p) { require(p==40 || p==36 || p==12 || p==38 || p==31,"Pin outside HAT profile"); }
    void check() { require(errno==0,"WiringPi GPIO operation failed"); }
public:
    explicit Hal(std::string device) : RadioLibHal(INPUT,OUTPUT,LOW,HIGH,INT_EDGE_RISING,INT_EDGE_FALLING),path(std::move(device)) {}
    ~Hal() override { term(); }
    void init() override {
        if(initialized) return;
        std::ifstream in("/sys/firmware/devicetree/base/compatible",std::ios::binary);
        std::string dt((std::istreambuf_iterator<char>(in)),{});
        std::istringstream entries(dt); std::string entry; bool board=false, soc=false;
        while(std::getline(entries,entry,'\0')) { board |= entry=="xunlong,orangepi-zero2w"; soc |= entry=="allwinner,sun50i-h618"; }
        require(board && soc,"Expected Orange Pi Zero 2W / H618");
        require(wiringPiSetupPhys()==0,"WiringPi H618 setup failed");
        require(physPinToGpio(40)==259 && physPinToGpio(36)==76,"Wrong WiringPi board mapping");
        initialized=true;
        spiBegin();
    }
    void term() override {
        callback=nullptr;
        // Best effort: do not throw from destructors or hide the original failure.
        if(owned.count(31)) ::digitalWrite(31,LOW);
        if(owned.count(40)) ::digitalWrite(40,HIGH);
        for(auto p:owned) ::pinMode(p,PM_OFF);
        owned.clear(); spiEnd(); initialized=false;
    }
    void pinMode(uint32_t p,uint32_t mode) override {
        if(p==RADIOLIB_NC) return;
        pin(p); require(mode==INPUT || mode==OUTPUT,"Unsupported GPIO mode");
        errno=0; ::pinMode(p,mode); check(); owned.insert(p);
    }
    void digitalWrite(uint32_t p,uint32_t value) override {
        if(p==RADIOLIB_NC) return;
        pin(p); require(owned.count(p),"GPIO not owned");
        errno=0; ::digitalWrite(p,value); check();
    }
    uint32_t digitalRead(uint32_t p) override {
        if(p==RADIOLIB_NC) return 0;
        pin(p); require(owned.count(p),"GPIO not owned");
        errno=0; int v=::digitalRead(p); check(); require(v==0 || v==1,"GPIO read failed"); return v;
    }
    // Class A RadioLib callbacks set an RX/TX flag. Dispatch synchronously so
    // its flag is never accessed from a concurrent C GPIO worker thread.
    void attachInterrupt(uint32_t p,void (*cb)(),uint32_t mode) override {
        require(p==36 && mode==INT_EDGE_RISING,"Only DIO1 rising edge supported");
        pinMode(p,INPUT); callback=cb; previous=false;
    }
    void detachInterrupt(uint32_t p) override { require(p==36,"Unexpected IRQ"); callback=nullptr; }
    void yield() override {
        require(!stopping,"Stop requested; interrupted state will rejoin");
        if(callback) {
            bool level=digitalRead(36);
            bool rising=level && !previous; previous=level;
            if(rising) callback();
        }
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    RadioLibTime_t micros() override {
        return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-epoch).count();
    }
    RadioLibTime_t millis() override { return micros()/1000; }
    void delayMicroseconds(RadioLibTime_t us) override {
        auto start=micros(); do { yield(); } while(micros()-start<us);
    }
    void delay(RadioLibTime_t ms) override { delayMicroseconds(ms*1000); }
    long pulseIn(uint32_t,uint32_t,RadioLibTime_t) override { throw std::runtime_error("pulseIn is not used by this LoRaWAN HAL"); }
    void spiBegin() override {
        if(spi>=0) return;
        spi=open(path.c_str(),O_RDWR|O_CLOEXEC|O_NOFOLLOW);
        require(spi>=0,"Cannot open configured SPI device");
        struct stat st{}; require(fstat(spi,&st)==0 && S_ISCHR(st.st_mode),"Expected SPI character device");
        uint32_t mode=SPI_MODE_0|SPI_NO_CS, actual=0, speed=2000000; uint8_t bits=8;
        require(ioctl(spi,SPI_IOC_WR_MODE32,&mode)==0 && ioctl(spi,SPI_IOC_RD_MODE32,&actual)==0 && actual==mode &&
                ioctl(spi,SPI_IOC_WR_BITS_PER_WORD,&bits)==0 && ioctl(spi,SPI_IOC_WR_MAX_SPEED_HZ,&speed)==0,
                "SPI must support mode 0, 8 bits, 2 MHz and software CS");
    }
    void spiBeginTransaction() override {}
    void spiEndTransaction() override {}
    void spiTransfer(uint8_t* out,size_t count,uint8_t* in) override {
        require(spi>=0 && count<=4096,"Invalid SPI transfer");
        spi_ioc_transfer t{}; t.tx_buf=reinterpret_cast<uintptr_t>(out); t.rx_buf=reinterpret_cast<uintptr_t>(in);
        t.len=count; t.speed_hz=2000000; t.bits_per_word=8;
        require(ioctl(spi,SPI_IOC_MESSAGE(1),&t)==static_cast<int>(count),"SPI transfer failed");
    }
    void spiEnd() override { if(spi>=0) close(spi); spi=-1; }
};
}
