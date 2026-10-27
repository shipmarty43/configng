// SPDX-License-Identifier: GPL-3.0-or-later
#include "node.hpp"
#include <filesystem>
#include <iostream>
#include <sys/wait.h>

using namespace lw;
namespace {
unsigned checks=0;
void test(bool ok) { require(ok,"Test assertion failed"); ++checks; }
template<class Fn> void rejects(Fn fn) { bool caught=false; try { fn(); } catch(const std::exception&) { caught=true; } test(caught); }
const std::string config="schema=1\nenabled=false\nwiring_verified=false\nregion=EU433\nclass=A\nactivation=OTAA-1.0.4\nspidev=/dev/spidev1.0\ninterval_seconds=300\nfport=10\nconfirmed=false\npayload_hex=010203\n";
const std::string keys="join_eui=0000000000000000\ndev_eui=0102030405060708\napp_key=0102030405060708090a0b0c0d0e0f10\n";
// No fake successful radio exchange: every hardware method fails if called.
class NoHardware : public RadioLibHal {
public:
    NoHardware():RadioLibHal(0,1,0,1,1,2){}
    void pinMode(uint32_t,uint32_t) override { throw std::runtime_error("unexpected hardware"); }
    void digitalWrite(uint32_t,uint32_t) override { throw std::runtime_error("unexpected hardware"); }
    uint32_t digitalRead(uint32_t) override { throw std::runtime_error("unexpected hardware"); }
    void attachInterrupt(uint32_t,void(*)(),uint32_t) override { throw std::runtime_error("unexpected hardware"); }
    void detachInterrupt(uint32_t) override { throw std::runtime_error("unexpected hardware"); }
    void delay(RadioLibTime_t) override { throw std::runtime_error("unexpected hardware"); }
    void delayMicroseconds(RadioLibTime_t) override { throw std::runtime_error("unexpected hardware"); }
    RadioLibTime_t millis() override { throw std::runtime_error("unexpected hardware"); }
    RadioLibTime_t micros() override { throw std::runtime_error("unexpected hardware"); }
    long pulseIn(uint32_t,uint32_t,RadioLibTime_t) override { throw std::runtime_error("unexpected hardware"); }
    void spiBegin() override { throw std::runtime_error("unexpected hardware"); }
    void spiBeginTransaction() override { throw std::runtime_error("unexpected hardware"); }
    void spiEndTransaction() override { throw std::runtime_error("unexpected hardware"); }
    void spiTransfer(uint8_t*,size_t,uint8_t*) override { throw std::runtime_error("unexpected hardware"); }
    void spiEnd() override { throw std::runtime_error("unexpected hardware"); }
};
class FixtureRadio : public SX1262 {
public:
    using SX1262::SX1262;
    uint8_t randomByte() override { return 0x42; }
};
class SessionFixture : public Node {
public:
    using Node::Node;
    void seed() {
        createSession();
        commitNonceFloor(7); nonces();
        std::copy_n(bufferNonces+RADIOLIB_LORAWAN_NONCES_SIGNATURE,2,
                    bufferSession+RADIOLIB_LORAWAN_SESSION_NONCES_SIGNATURE);
        sessionStatus=RADIOLIB_LORAWAN_SESSION_ACTIVE;
        fCntUp=42; aFCntDown=11; nFCntDown=9;
    }
    bool countersRestored() const { return fCntUp==42 && aFCntDown==11 && nFCntDown==9; }
    void exhaustCounter() { fCntUp=UINT32_MAX; }
};
}
int main() {
    try {
        auto c=Config::parse(config,keys);
        test(c.devEui==0x0102030405060708ULL && c.payload==Bytes({1,2,3}) && !c.enabled);
        rejects([&]{Config::parse(config+"enabled=true\n",keys);});
        rejects([&]{Config::parse(config+"unknown=value\n",keys);});
        for(auto [from,to] : std::vector<std::pair<std::string,std::string>>{
            {"EU433","EU868"},{"class=A","class=C"},{"300","1"},{"fport=10","fport=0"},
            {"fport=10","fport=224"},{"false","yes"},{"spidev1.0","spidev../0"},{"010203","zz"}}) {
            auto bad=config; bad.replace(bad.find(from),from.size(),to);
            rejects([&]{Config::parse(bad,keys);});
        }
        rejects([&]{Config::parse(config,keys+"nwk_key=00\n");});
        NoHardware hal; Module module(&hal,40,36,12,38); SX1262 radio(&module);
        Node node(&radio); node.credentials(c);
        Snapshot s{c.identity,node.nonces(),{},1234};
        test(Snapshot::decode(s.encode(),c.identity).nonces==s.nonces);
        auto bad=s.encode(); bad[bad.size()-3]='x';
        rejects([&]{Snapshot::decode(bad,c.identity);});
        rejects([&]{Snapshot::decode(s.encode(),"different identity");});
        // Simulate power loss after durable reservation but before/after RF TX:
        // a new node restores the next nonce, while the live node retains this one.
        s.nonces=node.reserveJoin(); test(node.nextNonce()==0);
        Node restarted(&radio); restarted.credentials(c); restarted.restore(s);
        test(restarted.nextNonce()==1 && !restarted.pending());
        node.commitNonceFloor(1); test(node.nextNonce()==1 && node.nonces()==s.nonces);
        node.commitNonceFloor(UINT16_MAX); rejects([&]{node.reserveJoin();});
        Snapshot shortState{c.identity,{1,2},{},0}; rejects([&]{restarted.restore(shortState);});
        auto other=c; other.appKey[0]^=1; Node wrong(&radio); wrong.credentials(other);
        rejects([&]{wrong.restore(s);});
        // Real RadioLib serialization/restoration of a synthetic session fixture.
        // This is deliberately not a simulated successful network join.
        FixtureRadio fixtureRadio(&module);
        SessionFixture active(&fixtureRadio); active.credentials(c); active.seed();
        Snapshot clean{c.identity,active.nonces(),active.session(),5000};
        SessionFixture resumed(&fixtureRadio); resumed.credentials(c); resumed.restore(clean);
        test(resumed.pending() && resumed.countersRestored() && resumed.nextNonce()==7);
        auto dirty=clean; dirty.session.clear();
        SessionFixture interrupted(&fixtureRadio); interrupted.credentials(c); interrupted.restore(dirty);
        test(!interrupted.pending() && !interrupted.isActivated() && interrupted.nextNonce()==7);
        auto corruptSession=clean; corruptSession.session[0]^=1;
        SessionFixture corrupt(&fixtureRadio); corrupt.credentials(c);
        rejects([&]{corrupt.restore(corruptSession);});
        active.exhaustCounter(); active.rejoinIfCounterExhausted();
        test(!active.isActivated() && active.nextNonce()==7);
        char name[]="/tmp/opi-lorawan-test-XXXXXX"; auto path=mkdtemp(name); require(path,"mkdtemp failed");
        {
            Store store(path); test(!store.exists()); store.save(s);
            test(store.load(c.identity).nonces==s.nonces);
            rejects([&]{Store second(path);});
            auto newer=s; newer.readyAt=9999; store.save(newer); test(store.load(c.identity).readyAt==9999);
            struct stat st{}; test(stat((std::string(path)+"/state").c_str(),&st)==0 && (st.st_mode&077)==0);
            // A child dies after saving a reservation; the parent sees durable
            // replacement, never a reconstructed zero nonce.
            pid_t pid=fork(); require(pid>=0,"fork failed");
            if(pid==0) { newer.readyAt=7777; store.save(newer); _exit(0); }
            int status=0; waitpid(pid,&status,0); test(WIFEXITED(status) && WEXITSTATUS(status)==0);
            test(store.load(c.identity).readyAt==7777);
            unlink((std::string(path)+"/state").c_str()); rejects([&]{store.load(c.identity);});
            symlink("/etc/passwd",(std::string(path)+"/state").c_str()); rejects([&]{store.load(c.identity);});
        }
        std::filesystem::remove_all(path);
        std::cout<<checks<<" checks passed; no GPIO/SPI/network access\n";
        return 0;
    } catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
}
