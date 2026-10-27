// SPDX-License-Identifier: GPL-3.0-or-later
#include "hal.hpp"
#include "node.hpp"
#include <iostream>
#include <ctime>

namespace {
uint64_t now() {
    auto n=time(nullptr);
    lw::require(n>=1767225600,"Set a trustworthy system clock before radio operations");
    return n;
}
void waitUntil(uint64_t t) {
    while(!lw::stopping && now()<t) std::this_thread::sleep_for(std::chrono::seconds(1));
}
struct Standby {
    SX1262& radio;
    ~Standby() { try { radio.standby(); } catch(...) {} }
};
}
int main(int argc,char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="--version") {
            std::cout<<"opi-lorawan 0.1; RadioLib "<<lw::revision<<"; EU433 OTAA-1.0.4 Class A\n"; return 0;
        }
        lw::require(argc==5,"Usage: opi-lorawan check|preflight|status|provision|run CONFIG CREDENTIALS STATE_DIRECTORY");
        const std::string action=argv[1];
        lw::require(action=="check" || action=="preflight" || action=="status" || action=="provision" || action=="run","Unknown action");
        auto c=lw::loadConfig(argv[2],argv[3]);
        if(action=="check" || action=="preflight") {
            if(action=="preflight") lw::require(c.enabled && c.verified,"LoRaWAN is disabled or wiring is not verified");
            std::cout<<"Configuration valid: EU433 Class A OTAA-1.0.4; enabled="<<c.enabled
                     <<" wiring_verified="<<c.verified<<"; hardware not probed\n"; return 0;
        }
        lw::Store store(argv[4]);
        // Constructing the HAL/module/node does not open any hardware.
        lw::Hal hal(c.spi); Module module(&hal,40,36,12,38); SX1262 radio(&module); lw::Node node(&radio);
        node.credentials(c);
        if(action=="status") {
            auto s=store.load(c.identity);
            node.restore(s);
            std::cout<<"State valid; saved_session="<<!s.session.empty()<<" next_operation_not_before="<<s.readyAt
                     <<"; connectivity not probed\n"; return 0;
        }
        if(action=="provision") {
            lw::require(!store.exists(),"State already exists; refusing to reset identity/counters");
            store.save({c.identity,node.nonces(),{},0});
            std::cout<<"Fresh identity state provisioned; no hardware accessed\n"; return 0;
        }
        lw::require(c.enabled && c.verified,"Enable only after verifying HAT revision, SPI route, software CS and RF switch");
        auto state=store.load(c.identity); node.restore(state);
        lw::Fd owner(open("/run/lock/opi-radio.lock",O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600));
        lw::privateFile(owner.n);
        lw::require(flock(owner.n,LOCK_EX|LOCK_NB)==0,"Radio is owned by another service");
        signal(SIGINT,[](int){lw::stopping=1;}); signal(SIGTERM,[](int){lw::stopping=1;});
        waitUntil(state.readyAt); if(lw::stopping) return 0;
        // Waveshare crystal profile: never apply another module's TCXO voltage.
        radio.tcxoVoltage=0;
        ConfigLoRa_t rf; rf.frequency=433.175; rf.power=10;
        lw::require(radio.begin(rf)==RADIOLIB_ERR_NONE,"SX1262 initialization failed");
        Standby cleanup{radio};
        lw::require(radio.setDio2AsRfSwitch(true)==RADIOLIB_ERR_NONE,"DIO2 RF switch failed");
        radio.setRfSwitchPins(RADIOLIB_NC,31);
        node.setDutyCycle(true); node.setADR(true);
        if(node.pending()) {
            lw::require(node.activateOTAA()==RADIOLIB_LORAWAN_SESSION_RESTORED,"Session resume failed");
            std::cout<<"session_restored\n"<<std::flush;
        }
        while(!lw::stopping) {
            waitUntil(state.readyAt); if(lw::stopping) break;
            // Durable write-ahead barrier. No previous session survives a crash
            // during RF exchange. A join also reserves its nonce before any TX.
            state.session.clear(); state.readyAt=now()+3600;
            int result=0;
            node.rejoinIfCounterExhausted();
            if(!node.isActivated()) {
                auto floor=static_cast<uint16_t>(node.nextNonce()+1);
                state.nonces=node.reserveJoin(); store.save(state);
                result=node.activateOTAA();
                node.commitNonceFloor(floor);
                std::cout<<"join_result="<<result<<"\n"<<std::flush;
            } else {
                state.nonces=node.nonces(); store.save(state);
                std::array<uint8_t,RADIOLIB_LORAWAN_MAX_PAYLOAD_SIZE+1> down{}; size_t count=0;
                LoRaWANEvent_t upEvent{},downEvent{};
                result=node.sendReceive(c.payload.data(),c.payload.size(),c.port,down.data(),&count,c.confirmed,&upEvent,&downEvent);
                lw::require(count<=down.size(),"Downlink exceeded receive buffer");
                std::cout<<"uplink_result="<<result<<" ack="<<downEvent.confirming<<" downlink_bytes="<<count;
                if(result>0) std::cout<<" downlink_port="<<unsigned(downEvent.fPort)<<" downlink_hex="<<lw::hex(lw::Bytes(down.begin(),down.begin()+count));
                std::cout<<"\n"<<std::flush;
            }
            bool success=result>=0 || result==RADIOLIB_LORAWAN_NEW_SESSION || result==RADIOLIB_LORAWAN_SESSION_RESTORED;
            // A failed transmit can be ambiguous; never retry an old frame
            // counter in that session, even without a process restart.
            if(!success) node.clearSession();
            state.nonces=node.nonces();
            if(node.isActivated() && success) state.session=node.session();
            state.readyAt=now()+(success?std::max<uint64_t>(c.interval,(node.timeUntilUplink()+999)/1000):3600);
            store.save(state);
        }
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"opi-lorawan: "<<e.what()<<"\n"; return 1;
    }
}
