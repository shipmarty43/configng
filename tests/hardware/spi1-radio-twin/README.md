# Three SPI1 radios on Orange Pi Zero 2W

| Logical endpoint | Device | Active-low select on the 40-pin header | Other signals |
|---|---|---|---|
| CS0 | Waveshare SX1262 433 MHz SPI/GNSS | 40 / PI3 | RESET 12, BUSY 38, DIO1 36, antenna switch 31 (high selects RX) |
| CS1 | CC1101 | 26 / PH9 | GDO inputs optional, unassigned in this profile |
| CS2 | nRF24L01 | 24 / PH5 | CE on 18 / PH4 |

The modules share SCLK 23, MOSI 19, MISO 21 and ground. The HAT dictates CS0.
CS1 preserves the earlier CC1101 route. Pin 24 is the proposed separate CSN
wire for nRF24. The three Linux GPIO chip-select descriptors keep PH5 and PH9
in GPIO mode so the logical numbering can differ from the native mux. CE and
the antenna switch are independent of CS. No boot service or transmit operation
is selected by the overlay. [Canonical device-tree overlay](../../../share/armbian-config/overlays/opi-zero2w-spi1-radios.dts)

## Selecting and restoring the profile

In DTO001 choose the SPI1 radio profiles, then **shared**. The API equivalent is
`armbian-config-zero2w --api module_sx1262_overlay shared`. This compiles the
bundled DTS, installs its immutable DTBO under `/boot/overlay-user`, verifies the
composed board tree and backs up the next-boot selection. It atomically replaces
the managed single-HAT token. Other SPI1 providers or overlapping pad owners
must be resolved before saving. The new selection takes effect after reboot.
`status` reports next-boot selection and bound live endpoints separately.

`enable` selects a previously installed single-HAT overlay, `disable` removes
the managed radio selection and `rollback change.ID` restores a saved change.
Clear dependent SPI001 CS1/CS2 overrides before removing their provider.
SXMD01 controls the SX1262 SPI request. SPI001 sets the separate CC1101 and
nRF24 ceilings. The overlay ceilings are 16 MHz, 6.5 MHz and 8 MHz in CS order.

Use the matching armbian-gui `opi-zero2w-spi1-radios.yaml` profile. Its three
diagnostic pages discover the Linux bus by OF identity. On demand they read
SX1262 GetStatus, CC1101 PARTNUM/VERSION/MARCSTATE and nRF24 CONFIG/RF_CH/RPD
with CE low. The core package includes the overlay and per-device lock files.
The GUI and optional separately built LoRaWAN program need the shared-route
update when using this three-client tree. Meshtastic and Reticulum use the
configurator's SX1262 route discovery. [GUI profile](https://github.com/shipmarty43/armbian-gui/blob/codex/opi-hardware-bringup/config/opi-zero2w-spi1-radios.yaml)

## Ownership

Locks belong to the physical header controller and logical CS across Linux
bus renumbering. CS0 keeps `/run/lock/opi-radio.lock` for compatibility with
the native SX1262 service and mode switcher. CS1 and CS2 use
`/run/lock/opi-spi1-cs1.lock` and `/run/lock/opi-spi1-cs2.lock`. The SPI core
serializes messages while different file descriptors remain open. Advisory
locking applies to cooperating applications. Upgrade and restart older
CC1101/nRF24 GUI instances, which used the CS0 lock for their diagnostics.

## Offline acceptance, 28 November 2026

The H618 Armbian 6.18.57 distribution DTB had SHA-256
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
The shared overlay coexisted with the I²C1 and PWM1 routes. Tests switched
between single and shared profiles, checked idempotence and explicit rollback,
and rejected a foreign SPI provider, collisions on all eight CS/control pads
and removal with outstanding per-CS clock overrides.

The ARM64 guest used one Linux SPI controller, three spidev clients and a
memory-backed GPIO provider. The board DT and guest DT received the same
production radio and clock blobs. The controller was enumerated as Linux bus 7.
The device models independently checked the physical select bitmap, actual
transfer request, CE for nRF24 and the read opcode. In 32 synchronized rounds
plus cross-process contention tests the models accepted 35, 105 and 105
transfers at 2 MHz, 1 MHz and 4 MHz respectively. Every transfer selected only
its intended pad; overlaps and rejected commands were both zero. All CS lines
finished inactive. The CS0 contender was the native LoRaWAN lock-test binary.
For each occupied CS the same client was refused, the other two succeeded,
and killing the holder released the lock. These are virtual chip-select and
protocol checks. Header voltage, SCLK timing and real device responses await
bench confirmation.

With a prepared ARM64 kernel/header pair, the project's ARM64 Python/gpio/spidev
test initramfs, dtc/libfdt, QEMU and a cross compiler installed, run

```sh
bash tests/hardware/spi1-radio-twin/check-overlay.sh "$ALLWINNER_DTB_DIR" "$SINGLE_HAT_DTBO"
bash tests/hardware/spi1-radio-twin/run.sh "$IMAGE" "$HEADERS" "$ALLWINNER_DTB_DIR" \
  "$SX_PYTHON_INITRAMFS" "$GUI_CHECKOUT" "$NEW_WORKDIR"
python3 tests/hardware/spi1-radio-twin/live-routes.py "$NEW_WORKDIR/board.dtb" \
  "$GUI_CHECKOUT" "$LORAWAN_BUILD/lorawan-hal-tests"
```
