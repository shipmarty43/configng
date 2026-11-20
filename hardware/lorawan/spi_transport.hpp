// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <linux/spi/spidev.h>
#include <sys/ioctl.h>
#include <filesystem>
#include <fstream>

namespace lw {
inline uint32_t selectedSpiHz(uint32_t dtLimit, const std::filesystem::path& path="/etc/armbian-config/sx1262-spi-hz") {
    auto limit=std::min(dtLimit, uint32_t(2000000));
    require(limit>0,"Invalid SX1262 device-tree SPI clock");
    if(!std::filesystem::exists(path)) return limit;
    std::ifstream file(path, std::ios::binary);
    require(file.good(),"Cannot read SPI clock setting");
    std::string text((std::istreambuf_iterator<char>(file)), {});
    if(!text.empty() && text.back()=='\n') text.pop_back();
    uint32_t hz=0;
    auto [end,err]=std::from_chars(text.data(),text.data()+text.size(),hz);
    require(text.size()<=7 && err==std::errc{} && end==text.data()+text.size() && hz>0 && hz<=limit,
            "SPI clock outside the board profile");
    return hz;
}
inline void configureSpi(int spi, uint32_t speed=2000000) {
    uint32_t mode=SPI_MODE_0, actual=0, actualSpeed=0; uint8_t bits=8, actualBits=0, msb=0, actualLsb=1;
    require(ioctl(spi,SPI_IOC_WR_MODE32,&mode)==0 && ioctl(spi,SPI_IOC_RD_MODE32,&actual)==0 && actual==mode &&
        ioctl(spi,SPI_IOC_WR_LSB_FIRST,&msb)==0 && ioctl(spi,SPI_IOC_RD_LSB_FIRST,&actualLsb)==0 && actualLsb==0 &&
        ioctl(spi,SPI_IOC_WR_BITS_PER_WORD,&bits)==0 && ioctl(spi,SPI_IOC_RD_BITS_PER_WORD,&actualBits)==0 && actualBits==bits &&
        ioctl(spi,SPI_IOC_WR_MAX_SPEED_HZ,&speed)==0 && ioctl(spi,SPI_IOC_RD_MAX_SPEED_HZ,&actualSpeed)==0 && actualSpeed==speed,
        "SPI must support mode 0, MSB first, 8 bits, selected clock and kernel CS");
}
inline void transferSpi(int spi, uint8_t* out, size_t count, uint8_t* in, uint32_t speed=2000000) {
    require(spi>=0 && count<=4096,"Invalid SPI transfer");
    spi_ioc_transfer t{}; t.tx_buf=reinterpret_cast<uintptr_t>(out); t.rx_buf=reinterpret_cast<uintptr_t>(in);
    t.len=count; t.speed_hz=speed; t.bits_per_word=8;
    require(ioctl(spi,SPI_IOC_MESSAGE(1),&t)==static_cast<int>(count),"SPI transfer failed");
}
}
