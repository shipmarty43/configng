// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <RadioLib.h>
#include <wiringPi.h>
#include <wiringPiH618Line.h>
#include "spi_route.hpp"
#include <sys/sysmacros.h>
#include "spi_transport.hpp"
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
    uint32_t spiHz = 0;
    std::map<unsigned,int> owned;
    void (*callback)() = nullptr;
    bool previous = false;
    bool initialized = false;
    std::chrono::steady_clock::time_point epoch = std::chrono::steady_clock::now();
    void pin(unsigned p) { require(p==36 || p==12 || p==38 || p==31,"Pin outside HAT profile"); }

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
        require(wiringPiH618LineABI()==1 && wiringPiH618HeaderToNative(36)==76, "Wrong WiringPi H618 ABI or mapping");
        spiBegin();
        pinMode(38,INPUT);
        pinMode(36,INPUT);
        pinMode(31,OUTPUT);
        pinMode(12,OUTPUT);
        initialized=true;
    }
    void term() override {
        callback=nullptr;
        if(owned.count(31)) wiringPiH618LineWrite(owned.at(31), LOW);
        for(auto [pin, fd]:owned) close(fd);
        owned.clear(); spiEnd(); initialized=false;
    }
    void pinMode(uint32_t p,uint32_t mode) override {
        if(p==RADIOLIB_NC) return;
        pin(p);
        const bool output = p==12 || p==31;
        require(mode==(output ? OUTPUT : INPUT), "Incorrect direction for HAT pin");
        if(owned.count(p)) return;
        int fd=wiringPiH618LineRequest(p,output ? WPI_H618_OUTPUT : WPI_H618_INPUT,
                                       p==12, WPI_H618_BIAS_DEFAULT,WPI_H618_NO_EDGE,0);
        require(fd>=0,"Cannot claim physical pin " + std::to_string(p));
        owned.emplace(p,fd);
    }
    void digitalWrite(uint32_t p,uint32_t value) override {
        if(p==RADIOLIB_NC) return;
        require(owned.count(p) && (p==12 || p==31) && wiringPiH618LineWrite(owned.at(p),value)==0, "GPIO write failed");
    }
    uint32_t digitalRead(uint32_t p) override {
        if(p==RADIOLIB_NC) return 0;
        require(owned.count(p),"GPIO not owned");
        int v=wiringPiH618LineRead(owned.at(p));
        require(v==0 || v==1,"GPIO read failed");
        return v;
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
        auto device = path=="auto" ? discoverSpi() : fs::path(path);
        spi=open(device.c_str(),O_RDWR|O_CLOEXEC|O_NOFOLLOW);
        require(spi>=0,"Cannot open configured SPI device");
        struct stat st{}; require(fstat(spi,&st)==0 && S_ISCHR(st.st_mode),"Expected SPI character device");
        auto dev = std::to_string(major(st.st_rdev)) + ":" + std::to_string(minor(st.st_rdev));
        validateRoute("/sys/firmware/devicetree/base/soc", fs::path("/sys/dev/char")/dev/"device/of_node");
        auto raw = property(fs::path("/sys/dev/char")/dev/"device/of_node/spi-max-frequency");
        require(raw.size()==4,"Invalid SPI clock DT cell");
        uint32_t limit;
        std::memcpy(&limit,raw.data(),sizeof(limit));
        spiHz = selectedSpiHz(ntohl(limit));
        configureSpi(spi,spiHz);
    }
    void spiBeginTransaction() override {}
    void spiEndTransaction() override {}
    void spiTransfer(uint8_t* out,size_t count,uint8_t* in) override {
        transferSpi(spi,out,count,in,spiHz);
    }
    void spiEnd() override { if(spi>=0) close(spi); spi=-1; }
};
// Waveshare's external switch is HIGH for RX, LOW for TX and idle.
inline void configureSwitch(Module& module) { module.setRfSwitchPins(31, RADIOLIB_NC); }
}
