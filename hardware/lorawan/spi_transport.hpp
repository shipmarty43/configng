// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <linux/spi/spidev.h>
#include <sys/ioctl.h>

namespace lw {
inline void configureSpi(int spi) {
    uint32_t mode=SPI_MODE_0, actual=0, speed=2000000, actualSpeed=0; uint8_t bits=8, actualBits=0;
    require(ioctl(spi,SPI_IOC_WR_MODE32,&mode)==0 && ioctl(spi,SPI_IOC_RD_MODE32,&actual)==0 && actual==mode &&
        ioctl(spi,SPI_IOC_WR_BITS_PER_WORD,&bits)==0 && ioctl(spi,SPI_IOC_RD_BITS_PER_WORD,&actualBits)==0 && actualBits==bits &&
        ioctl(spi,SPI_IOC_WR_MAX_SPEED_HZ,&speed)==0 && ioctl(spi,SPI_IOC_RD_MAX_SPEED_HZ,&actualSpeed)==0 && actualSpeed==speed,
        "SPI must support mode 0, 8 bits, 2 MHz and kernel CS");
}
inline void transferSpi(int spi, uint8_t* out, size_t count, uint8_t* in) {
    require(spi>=0 && count<=4096,"Invalid SPI transfer");
    spi_ioc_transfer t{}; t.tx_buf=reinterpret_cast<uintptr_t>(out); t.rx_buf=reinterpret_cast<uintptr_t>(in);
    t.len=count; t.speed_hz=2000000; t.bits_per_word=8;
    require(ioctl(spi,SPI_IOC_MESSAGE(1),&t)==static_cast<int>(count),"SPI transfer failed");
}
}
