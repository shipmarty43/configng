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
    const uint32_t pi3ActiveLow[] = {htonl(8), htonl(3), htonl(1)};
    const std::string descriptor(reinterpret_cast<const char*>(pi3ActiveLow), sizeof(pi3ActiveLow));
    require(sx1262 && property(node/"reg") == std::string(4, '\0') && !fs::exists(node/"spi-cs-high")
            && pioHandle.size() == 4 && property(ctrl/"cs-gpios") == pioHandle + descriptor,
            "Expected kernel CS0 on PI3 (physical 40, active low)");
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
