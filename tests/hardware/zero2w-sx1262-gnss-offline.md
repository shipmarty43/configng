# Zero 2W radio and GNSS offline acceptance, 2026-11-20

| Path exercised | Result |
|---|---|
| Actual Armbian 6.18.57 board DTB, SPI1 HAT, DFR0528, i2c1-pi and pwm1-pi11 | HAT enable and repeated enable passed. A conflicting enabled SPI child was rejected from both overlay menus. Disable and matching rollback preserved the original UPS/PWM selections. A later manual edit prevented rollback. |
| CPU-native and AArch64 LoRaWAN binaries | Configuration, persistence, GPIO failure cleanup, RadioLib RX/TX/idle switch table, live-route positive/negative fixtures and process contention passed. AArch64 binaries ran under qemu-user. |
| Native C++ SPI transport, full-system AArch64 QEMU | Production ioctl setup read back mode 0, 8 bits and 2 MHz. Separate two-byte transfers returned 00/00 and FF/FF with the virtual MISO pulled down and up. |
| Python HAT driver and C++ HAL lock | Each implementation blocked while the other held the same inode. Killing either holder released the lock. |
| Python HAT driver, full-system QEMU | 16 tests passed using the WiringPi checked ABI, gpio-sim and spi-gpio. Scripted responses exercised the packet paths. The guest used one CPU and 256 MiB. |
| GNSS selection | Tests cover manual, off, auto failover and recovery, repeated/expired samples, frozen clock, out-of-order reports, invalid checksums and coordinates. |
| Waveshare receive path | Generated RMC/GGA over a PTY went through real gpsd 3.27.5 into a timestamped fix. |
| SIM7600 receive path | A fixture on a private D-Bus advertised the model and GPS-NMEA source, and returned an RMC trace. The host's actual mmcli serialized it for the production adapter. |
| Configurator | UPS, LoRaWAN and GNSS Bats tests passed. Tested selection and rollback against a scratch boot directory. |

The stock DTB SHA-256 was
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
Use `tests/hardware/check-sx1262-overlays.sh` with that board DTB and the four
DTBO paths listed by its usage message. Build the native tests as described in
[the LoRaWAN component](../../hardware/lorawan/README.md). For the QEMU SPI
check, build `lorawan-hal-tests` for AArch64, boot the armbian-gui spi-gpio
fixture, set its MISO pull and run `lorawan-hal-tests qemu-spi /dev/spidevN.0`
for both levels. The emulator kernel needs `CONFIG_FILE_LOCKING=y`. The GNSS
tests and package dependencies are in [the GNSS component](../../hardware/gnss/README.md).

## Board acceptance

1. Reboot with the HAT, UPS and PWM selections. Inspect the bound SPI endpoint
   and verify UPS percentage and existing PWM configuration survive.
2. Observe NSS on physical 40, switch on 31, RESET, BUSY and DIO1. Record a
   complete command frame, CS release and RX/TX transition on the actual shield.
3. With matching EU433 infrastructure, verify OTAA join, uplinks, RX1/RX2
   downlinks, ACKs and session recovery after power loss.
4. Confirm the L76K UART path and 9600-baud NMEA. Obtain a fresh outdoor fix.
   On the SIM7600 inspect GPS-NMEA availability and obtain a separate fix.
   Exercise disconnect/reconnect and recovery while mobile data remains up.
