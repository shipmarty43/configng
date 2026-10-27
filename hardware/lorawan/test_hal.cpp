// SPDX-License-Identifier: GPL-3.0-or-later
#include "hal.hpp"
#include <iostream>

// Link-time GPIO test doubles: this target never links the WiringPi library.
static std::map<int,int> modes,levels;
static int failPin=-1,edges=0;
extern "C" {
int wiringPiSetupPhys() { throw std::runtime_error("Hardware setup must not run in HAL unit tests"); }
int physPinToGpio(int) { return -1; }
void pinMode(int pin,int mode) {
    if(pin==failPin) { errno=EBUSY; return; }
    if(mode==PM_OFF) modes.erase(pin); else modes[pin]=mode;
}
void digitalWrite(int pin,int level) {
    if(pin==failPin) { errno=EIO; return; }
    levels[pin]=level;
}
int digitalRead(int pin) {
    if(pin==failPin) { errno=EIO; return -1; }
    return levels[pin];
}
}
static void edge() { ++edges; }
template<class F> void rejects(F fn) {
    bool failed=false; try {fn();} catch(const std::exception&) {failed=true;}
    lw::require(failed,"Expected rejection");
}
int main() {
    try {
        {
            lw::Hal hal("/no-such-device");
            rejects([&]{hal.pinMode(3,OUTPUT);});
            rejects([&]{hal.digitalWrite(40,1);});
            hal.pinMode(40,OUTPUT); hal.digitalWrite(40,HIGH);
            lw::require(levels[40]==HIGH,"CS write failed");
            failPin=12; rejects([&]{hal.pinMode(12,OUTPUT);});
            lw::require(!modes.count(12),"Failed request retained ownership"); failPin=-1;
            hal.pinMode(38,INPUT); failPin=38;
            rejects([&]{hal.digitalRead(38);}); failPin=-1;
            failPin=40; rejects([&]{hal.digitalWrite(40,0);}); failPin=-1;
            rejects([&]{hal.attachInterrupt(36,edge,INT_EDGE_FALLING);});
            hal.attachInterrupt(36,edge,INT_EDGE_RISING);
            levels[36]=1; hal.yield(); hal.yield();
            lw::require(edges==1,"Repeated high generated duplicate edge");
            levels[36]=0; hal.yield(); levels[36]=1; hal.yield();
            lw::require(edges==2,"Second edge missing");
            hal.detachInterrupt(36); levels[36]=0; hal.yield(); levels[36]=1; hal.yield();
            lw::require(edges==2,"Detached callback called");
            lw::stopping=1; rejects([&]{hal.yield();}); lw::stopping=0;
            rejects([&]{hal.spiBegin();});
        }
        lw::require(modes.empty(),"GPIO requests leaked on destruction");
        lw::require(levels[40]==HIGH,"CS not deasserted on cleanup");
        std::cout<<"HAL pin restriction, GPIO failures, edge dispatch, cancellation and cleanup: passed (test doubles)\n";
    } catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
}
