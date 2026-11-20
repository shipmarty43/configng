# H616/H618 SPI clock acceptance, 2026-11-21

The implementation and reproduction commands are in the [clock guide](../../hardware/sx1262-mode/spi-clock.md).
The test used Armbian 26.11.0-trunk.108, ARM64, Linux 6.18.57, and the
Waveshare SPI HAT profile. No physical storage, SPI, GPIO or network
interface was passed to the guests.

| Check | Observation |
|---|---|
| Driver comparison | Compiled the CDR selection block from Linux 6.18.57 `spi-sun6i.c` and the divider search from `ccu_mp.c` with in-memory clock/register stubs. All 38,938 combinations agreed with the Python estimate in both CCR field and integer effective frequency. The inputs included CDR/CCU boundaries ±1 Hz, two sets of parent rates and four initial MCLKs. |
| Full hardware grid | For example parents of 24/600/600/1200/1200 MHz, all 6,450 unique in-range rational outputs matched their reported CCU and CCR fields. The Linux view has 283 request transitions with initial MCLK 24 MHz. |
| DT composition | Both the previous 2 MHz DTBO and the new 16 MHz DTBO passed the overlay manager on the original Armbian DTB, together with I²C, DFR0528 and PWM. Conflicting chip selects were rejected and rollback preserved the other overlays. |
| UI and backends | Menu tests covered typed Hz, selecting the integer request for a fractional grid row, cancellation and read-only SPI0 inspection. Meshtastic YAML, RNode ioctl framing and the standalone Python driver accepted the new endpoint limit. The ARM64 LoRaWAN HAL accepted a 16 MHz setting with the new DT ceiling and rejected the same file with the old ceiling. |
| Clean ARM64 package install | On a fresh qcow2 layer, the packaged CLI listed a 100 MHz controller row. With a disabled 16 MHz DT endpoint it saved 16,000,000, rejected 16,000,001 without replacing the saved value and reset to 2 MHz. Both hardware units stayed inactive. Guest RAM was 640 MiB, host cgroup peak 749.2 MiB and writable disk usage 167 MiB. |
| Interactive selection | A real dialog in a PTY, using a synthetic DT ceiling and the example parents, saved the 15 MHz HAT grid row to the shared-format setting file. |
| ARM64 kernel spidev | A separate 256 MiB QEMU guest used Linux `spi-gpio` and `gpio-sim`. All 17 standalone-driver tests passed. Requests of 2 and 16 MHz both passed spidev ioctl readback and transfers with virtual MISO held low and high. |

All frequency values in these checks are requests, register calculations or
kernel API readbacks. Pin 23 SCLK and the SX1262 MISO setup/hold margin
still require a physical measurement.
