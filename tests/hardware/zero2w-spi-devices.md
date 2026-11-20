# Per-device SPI clock acceptance on Zero 2W

Tested on 21 November 2026 with the Armbian 26.11.0-trunk.108 Zero 2W
image, kernel 6.18.57 and stock DTB SHA-256
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
The [SPI device clock guide](../../hardware/sx1262-mode/spi-devices.md)
describes the terminal menu and CLI.

| Test | Result |
|---|---|
| Original board DT | SPI0/CS0 was a JEDEC flash node with a 40 MHz board maximum. The header controller had no enabled devices until its device overlay was selected. |
| Independent settings | Three concurrent/sequential changes on both controllers composed into SPI0/CS0 18 MHz, SPI1/CS0 2 MHz and SPI1/CS1 5 MHz. Resetting SPI1/CS0 restored its default while preserving the other two settings. |
| Saved four-CS header overlay | The existing `spidev_spi1_cs4_pi3.dtbo` provided four logical chip selects. The resulting CS0…CS3 settings were 10, 10, 1 and 4 MHz. |
| Transaction and rollback | Reapplying the same clock preserved the boot file. Out-of-range requests, an absent CS, removing a required provider, swapping the chip at the same DT path, and a modified clock DTBO were rejected. A manual edit prevented rollback. An exact rollback restored the previous selections. |
| Real terminal | With a PTY and a disposable boot directory, the actual dialog selected SPI1/CS2 and stored a manual request of 700,000 Hz. SPI1/CS3 remained at 4 MHz. |
| Application limits | The CC1101, PN532 and nRF24 clients use the per-CS setting when present and retain the preexisting defaults otherwise. Tests exercised different controller numbers, different CS on one controller, a lower DT ceiling, a higher request bounded by the client and malformed/mismatched DT cells. |
| Clean ARM64 install | The current packages installed on an isolated stock image. The installed `SPI001` dialog rendered. Its public CLI wrote a flash CS0 clock of 18 MHz to the guest boot configuration and the selected DTBO composed to that value. Rollback restored the original boot environment byte for byte. |
| Kernel readback | A second ARM64 guest booted two spi-gpio controllers over virtual GPIO, with five spidev devices. Applying the same generated DTBOs gave 18 MHz on SPI0/CS0, and 10, 10, 1, 4 MHz on SPI1/CS0…CS3 in the first reads of SPI_IOC_RD_MAX_SPEED_HZ. The two unmarked clients retained their own 2 MHz test default. |

To repeat the DT transaction suite, run
`tests/hardware/check-spi-clocks.sh /path/to/sun50i-h618-orangepi-zero2w.dtb`
with dtc, fdtget and fdtoverlay available. It operates on temporary copies.
Actual SCLK and timing margins on the header require measurements on the board.
