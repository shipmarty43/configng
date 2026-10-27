// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <RadioLib.h>

namespace lw {
// Protected fields are deliberately coupled to the exact RadioLib revision.
// A dependency update must rerun the nonce reservation/restore tests.
class Node : public LoRaWANNode {
public:
    explicit Node(PhysicalLayer* radio) : LoRaWANNode(radio,&EU433) {}
    void credentials(const Config& c) {
        require(beginOTAA(c.joinEui,c.devEui,nullptr,c.appKey.data())==RADIOLIB_ERR_NONE,"OTAA configuration failed");
    }
    Bytes nonces() { auto p=getBufferNonces(); return Bytes(p,p+RADIOLIB_LORAWAN_NONCES_BUF_SIZE); }
    Bytes session() { auto p=getBufferSession(); return Bytes(p,p+RADIOLIB_LORAWAN_SESSION_BUF_SIZE); }
    uint16_t nextNonce() const { return devNonce; }
    void rejoinIfCounterExhausted() { if(fCntUp==UINT32_MAX) clearSession(); }
    Bytes reserveJoin() {
        require(devNonce<UINT16_MAX,"DevNonce exhausted; provision a new device identity");
        auto before=nonces();
        LoRaWANNode::hton<uint16_t>(&bufferNonces[RADIOLIB_LORAWAN_NONCES_DEV_NONCE],devNonce+1);
        auto reserved=nonces();
        std::copy(before.begin(),before.end(),bufferNonces);
        return reserved;
    }
    void commitNonceFloor(uint16_t floor) {
        devNonce=std::max(devNonce,floor);
        LoRaWANNode::hton<uint16_t>(&bufferNonces[RADIOLIB_LORAWAN_NONCES_DEV_NONCE],devNonce);
    }
    void restore(const Snapshot& s) {
        require(s.nonces.size()==RADIOLIB_LORAWAN_NONCES_BUF_SIZE,"Wrong nonce buffer length");
        require(setBufferNonces(s.nonces.data())==RADIOLIB_ERR_NONE,"Nonce buffer rejected; refusing reset");
        if(!s.session.empty()) {
            require(s.session.size()==RADIOLIB_LORAWAN_SESSION_BUF_SIZE,"Wrong session buffer length");
            require(setBufferSession(s.session.data())==RADIOLIB_ERR_NONE,"Session rejected; refusing reset");
        }
    }
    bool pending() const { return sessionStatus==RADIOLIB_LORAWAN_SESSION_PENDING; }
};
}
