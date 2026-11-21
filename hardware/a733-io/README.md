# Orange Pi Zero 3W header buses

Open **System → Hardware → A733 header buses** (`A733IO`) in this configng fork. The module checks the Zero 3W and SoC compatibles, composes stock and user overlays in boot order, checks pin claims including sleep states and stores the validated selection in armbianEnv.txt with a rollback copy. Settings apply at the next boot. UART framing is restored on tty discovery after checking the live mux, kernel console, getty, gpsd and open file descriptors.

| Route | Physical header | Settings |
|---|---|---|
| SPI2 | SCLK 13, MOSI 5, MISO 3. CS0 11, CS1 7, CS2 12, CS3 35 | Choose extra native selects independently. For each declared peripheral select `spi2-cs0` through `spi2-cs3` to set a frequency ceiling and mode 0–3. The cap comes from that peripheral's own DT binding. |
| SPI3 | SCLK 23, MOSI 19, MISO 21, CS0 24, CS1 26 | Each CS has its own frequency ceiling and SPI mode 0–3. Stock spidev endpoints request 500 kHz. The vendor driver minimum is 187,500 Hz and the silicon limit is 100 MHz. Select a ceiling supported by the attached peripheral. |
| I²C0 / 1 / 2 / 3 | SCL/SDA 5/3, 40/38, 23/19, 21/26 | Select 100 or 400 kHz for the entire bus. |
| UART2 / 6 / 7 | TX/RX 11/13, 24/23, 16/18 | Enable the header route and save baud, data bits, parity and stop bits. UART7 is the vendor name for S_UART0. |
| Reserved routes | UART0 debug 8/10, UART1 used for Bluetooth. Header 28/27 can mux S_TWI2; the enabled vendor S_TWI2 controller uses PL10/PL11 elsewhere. | These controllers retain their existing functions. UART8's vendor pins PL8/PL9 do not form a header pair. |

In the reference DTB the enabled camera subsystem reserves PE0 for MCLK. SPI3 and UART6 both claim PE0. The menu offers a separate explicit **Disable camera capture at next boot** action. Return the conflicting bus routes to default before restoring the camera. I²C2 and I²C3 also conflict with SPI3. Removing a managed override restores the selection provided by the base DT and other overlays.

Example API commands from the installed configurator:

```sh
armbian-config-zero2w --api module_a733_io list
armbian-config-zero2w --api module_a733_io grid spi3 24000000
armbian-config-zero2w --api module_a733_io set i2c0 400000
armbian-config-zero2w --api module_a733_io set uart2 on
armbian-config-zero2w --api module_a733_io save uart2 57600 8 none 1
armbian-config-zero2w --api module_a733_io backups
armbian-config-zero2w --api module_a733_io rollback change.ID
```

The grid takes a parent clock in Hz. For SPI3 the A733 CCU at offset 0x0f20 has two 5-bit linear divisors. For TWI the grid includes the M=0, 40% duty special case. UART uses a 16-bit divisor with 16× oversampling. Calculated grid entries and DT limits describe requested or nominal clocks. Actual clock selection and signal integrity require a measurement on the header. [A733 manuals and board schematics](../../tests/hardware/zero3w-port.md) · [Vendor CCU](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/clk/sunxi-ng/ccu-sun60iw2.c) · [Vendor SPI limits](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/spi-ng/spi-sunxi.h)

### Extra SPI2 selects and UART handshakes

CS1 uses PB4, CS2 uses PB5 and CS3 uses PB6. The vendor SPI driver accepts up to four native selects. Sparse selections mux only the chosen pads. With CS0 and CS3 selected, the controller advertises four addressable indices and the configurator rejects active children at indices 1 and 2. GPIO chip-select remapping and duplicate client addresses also fail validation. A device overlay supplies the actual chip binding. [Vendor SPI driver](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/spi-ng/spi-sunxi.c) · [SPI controller limits](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/spi-ng/spi-sunxi.h)

The reference DTB routes the vendor pin-test device's wake IRQ to PB6. To use CS3 select **Vendor pin-test IRQ and shared PB6 → Disable the vendor test device at next boot**, then add CS3. The two actions have separate backups. Releasing a CS requires clearing any clock override and removing or disabling its client. Restore the vendor test device after releasing CS3.

```sh
armbian-config-zero2w --api module_a733_io add-cs 1
armbian-config-zero2w --api module_a733_io set pinctrl-test release
armbian-config-zero2w --api module_a733_io add-cs 3
# Alternative: set the complete selected subset in one boot change.
armbian-config-zero2w --api module_a733_io set spi2 on 1 2 3
# Requires an enabled CS2 client with a declared limit of at least 500 kHz.
armbian-config-zero2w --api module_a733_io set spi2-cs2 500000 0
armbian-config-zero2w --api module_a733_io set uart6 rtscts
```

UART2 uses physical TX/RX/RTS/CTS **11/13/5/3** and UART6 uses **24/23/19/21**. Enabling UART6 first requires freeing PE0 from the camera. The active and sleep groups include all four pads. The idle-tty restore worker enables and reads back Linux `CRTSCTS` for the managed route. With no saved framing it preserves the tty's baud and character format. Select `set uartN on` for the two-wire route or roll back the boot change. A serial application that configures its own termios must also request RTS/CTS. [Cross-board DTB and PTY checks](../../tests/hardware/header-cs-rtscts.md)

## Offline acceptance

Armbian linux-dtb-vendor-sun60iw2 26.8.3, kernel 6.6.98, DTB SHA-256 `1eb1160f92dd1d566af920002583c67fbbb6eb35d190a62fb8f0bc1236bb74e1`. The packaged DTB identifies `xunlong,orangepi-zero3w`; the standalone Orange Pi source cited in the earlier assessment identifies 4 Pro. [Armbian package](https://apt.armbian.com/pool/main/l/linux-dtb-vendor-sun60iw2/) · [Armbian boot overlay order](https://github.com/armbian/build/blob/main/config/bootscripts/boot-sun60iw2.cmd)

```sh
bash tests/hardware/check-a733-io.sh /path/to/extracted/boot/dtb-6.6.98-vendor-sun60iw2/allwinner
python3 -B tests/hardware/test_a733_uart.py
```

The first check uses the full distribution DTB and a temporary boot directory. It exercises per-CS frequency and mode, all four I²C routes, all three UART routes, refusal of conflicts and rollback. The UART test uses synthetic sysfs and Linux PTY framing. Board boot, exact baud and SCLK, I²C rise times and physical exchanges are still hardware tests.
