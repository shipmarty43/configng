// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <arpa/inet.h>
#include <filesystem>
#include <fstream>
#include <set>

namespace lw {
namespace fs = std::filesystem;
inline std::string property(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    require(stream.good(), "Missing DT property: " + path.string());
    return std::string(std::istreambuf_iterator<char>(stream), {});
}
inline bool dtEnabled(const fs::path& node) {
    if (!fs::exists(node/"status")) return true;
    auto status = property(node/"status");
    return status == std::string("okay\0", 5) || status == std::string("ok\0", 3);
}
inline void validateRoute(const fs::path& soc, const fs::path& endpoint) {
    const auto ctrl = fs::canonical(soc/"spi@5011000");
    const auto pio = soc/"pinctrl@300b000";
    const auto group = pio/"spi1-pins";
    const auto node = fs::canonical(endpoint);
    require(node.parent_path() == ctrl && dtEnabled(ctrl) && dtEnabled(node), "Expected enabled H618 SPI1 radio");
    std::istringstream compat(property(node/"compatible"));
    std::string item;
    bool sx1262 = false;
    while (std::getline(compat, item, '\0')) sx1262 |= item == "semtech,sx1262";
    auto pioHandle = property(pio/"phandle"), groupHandle = property(group/"phandle");
    auto cell = [](uint32_t n) {
        n = htonl(n);
        return std::string(reinterpret_cast<const char*>(&n), sizeof(n));
    };
    auto gpio = [&](uint32_t bank, uint32_t line, uint32_t flags) {
        return pioHandle + cell(bank) + cell(line) + cell(flags);
    };
    std::string expected = gpio(8,3,1);
    const auto count = fs::exists(ctrl/"num-cs") ? property(ctrl/"num-cs") : cell(1);
    if (count == cell(3)) {
        expected += gpio(7,9,1) + gpio(7,5,1);
        const char* children[] = {"radio@0","cc1101@1","nrf24@2"};
        const char* kinds[] = {"semtech,sx1262","ti,cc1101","nordic,nrf24l01"};
        unsigned live = 0;
        for (const auto& peer : fs::directory_iterator(ctrl))
            if (peer.is_directory() && fs::exists(peer.path()/"reg") && dtEnabled(peer.path())) ++live;
        require(live == 3, "Unexpected shared SPI1 clients");
        for (unsigned i = 0; i < 3; ++i) {
            auto peer = ctrl/children[i];
            require(dtEnabled(peer) && property(peer/"reg") == cell(i) &&
                    property(peer/"compatible") == std::string(kinds[i]) + '\0' + "armbian,spi-dev" + '\0',
                    "Wrong shared SPI1 endpoint");
            for (auto flag : {"spi-cs-high","spi-cpha","spi-cpol","spi-3wire","spi-lsb-first"})
                require(!fs::exists(peer/flag), "Wrong shared SPI1 mode");
        }
        require(property(node/"reset-gpios") == gpio(8,1,1) && property(node/"busy-gpios") == gpio(8,4,0) &&
                property(node/"dio1-gpios") == gpio(2,12,0) && property(node/"rxen-gpios") == gpio(8,15,0),
                "Wrong Waveshare control lines");
        require(property(ctrl/"nrf24@2/ce-gpios") == gpio(7,4,0), "Wrong nRF24 CE");
    } else require(count == cell(1), "Unknown SPI1 radio layout");
    require(sx1262 && property(node/"reg") == cell(0) && !fs::exists(node/"spi-cs-high")
            && pioHandle.size() == 4 && property(ctrl/"cs-gpios") == expected,
            "Expected kernel CS0 on PI3 and qualified peer selects");
    std::set<std::string> pins;
    std::istringstream names(property(group/"pins"));
    while (std::getline(names, item, '\0')) pins.insert(item);
    require(groupHandle.size()==4 && property(ctrl/"pinctrl-0")==groupHandle &&
            property(group/"function")==std::string("spi1\0",5) && pins==std::set<std::string>{"PH6","PH7","PH8"},
            "Unexpected SPI1 pinmux");
    for (const auto& peer : fs::directory_iterator(ctrl)) {
        if (peer.path()!=node && peer.is_directory() && fs::exists(peer.path()/"reg") && dtEnabled(peer))
            require(property(peer.path()/"reg")!=std::string(4,'\0'), "Duplicate SPI1 CS0");
    }
}
inline fs::path discoverSpi(const fs::path& sysfs = "/sys") {
    auto soc = sysfs/"firmware/devicetree/base/soc";
    auto expected = fs::canonical(soc/"spi@5011000/radio@0");
    fs::path match;
    for (const auto& entry : fs::directory_iterator(sysfs/"class/spidev")) {
        const auto name = entry.path().filename().string();
        if (!name.starts_with("spidev") || !name.ends_with(".0")) continue;
        std::error_code ec;
        if (fs::equivalent(entry.path()/"device/of_node", expected, ec)) {
            require(match.empty(), "Ambiguous SX1262 endpoint");
            match = fs::path("/dev")/name;
        }
    }
    require(!match.empty(), "No spidev endpoint bound to the Waveshare HAT");
    return match;
}
}
