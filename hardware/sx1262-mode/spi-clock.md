# SPI clocks on the H616 and Orange Pi Zero 2W

The H616 specifies a 3 kHz to 100 MHz external SPI clock in master mode.
The Zero 2W uses an H618. Its Armbian 6.18.57 DTB identifies SPI1 as
`allwinner,sun50i-h616-spi` with the `allwinner,sun8i-h3-spi` fallback.
The following model matches that kernel's `spi-sun6i` H3 divider path.
[Allwinner H616 User Manual v1.0, §9.3.3.10, pp. 629–630](https://www.scs.stanford.edu/~zyedidia/docs/allwinner/h616.pdf#page=629) · [Linux SPI driver](https://github.com/torvalds/linux/blob/v6.18/drivers/spi/spi-sun6i.c)

| Stage | Source and divisors |
|---|---|
| Clock control unit (CCU) | SPI0 uses offset `0x940`, SPI1 uses `0x944`. The parent is OSC24M, PLL_PERI0 or PLL_PERI1 at 1× or 2×. MCLK = parent / (M × 2ᴺ), with M = 1…16 and N = 0…3. |
| SPI clock control register (CCR) | At controller offset `0x24`, DRS = 0 selects SCLK = MCLK / 2ᵐ, m = 0…15. DRS = 1 selects SCLK = MCLK / [2(n+1)], n = 0…255. |

The intervals between SCLK values vary. The raw silicon grid includes each
distinct output of both stages within the specified range. With the supplied
example of 24, 600, 600, 1200 and 1200 MHz, there are 6,450 distinct rates.
The register listing prints exact fractions in Hz alongside a parent, the encoded M/N fields and a CCR setting for each output. [Allwinner CCU, §§3.3.5.83–84](https://www.scs.stanford.edu/~zyedidia/docs/allwinner/h616.pdf#page=102) · [Allwinner SPI_CCR, §9.3.6.8](https://www.scs.stanford.edu/~zyedidia/docs/allwinner/h616.pdf#page=643)

Linux first tries CDR2 and falls back to CDR1 for larger divisors. If the
current MCLK is below twice the requested SCLK, the driver asks the CCU for
twice the request and reads MCLK again. Consequently a previous transfer
can change the grid for the next transfer. The configurator reads the CCF
clock rates in debugfs, when available. With an identified live MCLK but
missing parents it marks retunes unknown. With no verified MCLK it labels
the illustrative clock tree explicitly. Estimates reproduce Linux integer
Hz rounding. At the low end the output can fall below 3 kHz, or exceed a
small request if CDR1 saturates. These rows are marked in CLI output and
excluded from the menu's suggested settings. [Linux H616 CCU](https://github.com/torvalds/linux/blob/v6.18/drivers/clk/sunxi-ng/ccu-sun50i-h616.c) · [Linux CCU M/P rounding](https://github.com/torvalds/linux/blob/v6.18/drivers/clk/sunxi-ng/ccu_mp.c)

| Requested | Estimated SCLK, initially 24 MHz MCLK and the example parents |
|---:|---:|
| 500 kHz | 500 kHz |
| 5 MHz | 4 MHz |
| 12 MHz | 12 MHz |
| 16 MHz | 15 MHz, after changing MCLK to 30 MHz |
| 100 MHz, controller only | 100 MHz, after changing MCLK to 200 MHz |

## Select or inspect a clock

In **SXMD01 → SPI bus clock**, choose the HAT grid, type a request in Hz,
restore the default, or open the [per-device SPI0/SPI1 clock menu](spi-devices.md). Each HAT row stores the
smallest integer request that reaches its displayed rate for the snapshot.
For instance, 24 MHz / 14 requires a request of 1,714,286 Hz. Writing the
truncated value 1,714,285 would select the next larger divisor.

```sh
sudo armbian-config-zero2w --api module_sx1262_mode spi-grid hat
sudo armbian-config-zero2w --api module_sx1262_mode spi-grid spi1 --registers
sudo armbian-config-zero2w --api module_sx1262_mode spi-grid spi0 --mclk 24000000 --parents 24000000 600000000 600000000 1200000000 1200000000
sudo armbian-config-zero2w --api module_sx1262_mode spi 12000000
sudo armbian-config-zero2w --api module_sx1262_mode spi default
```

Reticulum, Meshtastic, the rebuilt LoRaWAN HAL and the updated standalone
Python driver read the shared integer-Hz setting on their next start.
The Waveshare SX1262 ceiling is the lower of the live DT property and
16 MHz. Semtech specifies a minimum SCK period of 62.5 ns at up to 10 pF
load. The default request is the lower of 2 MHz and the DT ceiling.
The previous 2 MHz overlay remains valid. The updated HAT overlay exposes
16 MHz after installing the DTBO in the existing overlay slot and booting
that configuration. The configurator's package installer does not modify
the boot partition. Restore the default before reverting to a client or DT
that only accepts 2 MHz. [Semtech SX1261/2 rev. 2.2, §8.2, table 8-1](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1177/DS_SX1261_2_V2-2.pdf#page=54) · [Zero 2W HAT overlay](https://github.com/shipmarty43/armbian-gui/blob/7b052bb6820744614e3f1579caa6e893c01986cf/hardware/overlays/opi-zero2w-sx1262.dts)

The offline tests cover both divider families, CCU retuning, fractional
boundaries, min/max settings, missing clocks, menu selection, host software
transports and both DTBO ceilings on the stock DTB. Electrical qualification
requires measuring SCLK on header pin 23 and checking MISO timing at the
intended speed under the actual HAT load. A read-only chip status transaction
in standby supplies the clocks for that measurement.
