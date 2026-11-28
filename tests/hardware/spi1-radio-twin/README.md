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

The extracted configurator package also opened the real dialog on a private boot
tree, selected the shared profile, installed the DTBO and saved the selection.
Run `package-menu.py CONFIGURATOR.deb ALLWINNER_DTB_DIR` with dialog and dtc
installed to repeat this check. The single-HAT regression suite passed 17 ARM64
tests separately. The shared-route check fed the same composed board tree and
five malformed variants to the GUI, mesh helper and C++ LoRaWAN validator.

### Bus and header profile panel

On Zero 2W, open **System → Шины и контакты (BUS002)** to compare live and
next-boot owners for all 28 signal pins. The panel resolves pinctrl, GPIO and
interrupt consumers in the composed board tree. The single Waveshare profile
also reserves its four fixed HAT sidebands. Live GPIO line-info reads supplement
the map when the kernel permits access. The SPI1 view includes spidev bindings,
advisory locks, requested speeds and DT ceilings in Hz.

The route list covers header I²C0–4 (including both I²C2 banks), UART2–5
(TX/RX and the supported RTS/CTS and RS-485 variants), PWM1–4 on their
alternative pads, and the SPI1 radio profiles. UART0 occupies pins 8/10 by
default. Use the dedicated console/PWM controls to release that reservation.
Preview reports both owners at each conflicting physical pin, and the boot
writer rechecks the same candidate under its lock. Dependency errors, such as
removing the I²C bus used by the DFR0528, also block saving.

Preview composes the candidate with Armbian's installed base DTB and overlays
in a temporary directory. Saving rechecks the preview under the boot writer's
lock. No reboot or SPI transfer is performed. Moving away from the shared
profile stores the immutable CS1/CS2 clock overlay names in
`opi_spi1_saved_clocks` in the same atomic environment update. Selecting
shared restores those clocks. SPI001 can inspect or clear a saved request.
One-step undo uses the matching record in
`/boot/armbianEnv.txt.spi1-panel-backups`; later unrelated edits require a new
preview. The legacy DTO001 profile selector uses the same clock preservation.

To repeat the cross-interface test with Python, Flask, PyYAML, urwid, jq,
dtc/libfdt and both checkouts available:

```sh
python3 tests/hardware/spi1-radio-twin/panel.py "$ALLWINNER_DTB_DIR" "$GUI_CHECKOUT"
```

An optional third argument points at the extracted package prefix. The fixture
builds the board DT and a private sysfs view, holds a real file lock and drives
the Web endpoints and both terminal menu handlers across independent processes.
It also exercises cancellation, stale previews, manual edits, an interrupted
rename and a corrupted saved clock overlay.

The same test covers I²C/UART/PWM route changes, blocked saves, the DFR0528,
GPIO-v2 line information on a model, and one-step undo across both interfaces.
Set `PANEL_TEST_CHROMIUM` to a Chromium executable for the optional headless
Web button test. It uses a temporary browser profile and a loopback Flask server.


### Zero 3W (A733)

BUS002 selects the board from the live OF compatible strings. On Zero 3W it
reads the vendor DTB and both GPIO controllers. The map covers all 28 signal
pins and identifies the debug UART on 8/10, camera MCLK on PE0 (24), and the
vendor pin-test IRQ on PB6 (35). The stock DT reserves 8/10 for both debug and
the pin-test device. These specific reservations remain visible when an
unrelated route is saved.

| Group | Next-boot choices |
| --- | --- |
| SPI | SPI2 clock/data on 13/5/3, CS0 on 11 and any subset of CS1/2/3 on 7/12/35. SPI3 clock/data on 23/19/21, CS0/1 on 24/26. Existing device clock/mode settings stay with their client. |
| I²C | TWI0–3 at 100 or 400 kHz. SCL/SDA pairs are 5/3, 40/38, 23/19 and 21/26. |
| UART | UART2 on 11/13, UART6 on 24/23, UART7 (standby UART0) on 16/18. Optional RTS/CTS on UART2 (5/3) and UART6 (19/21). |
| PWM | Vendor PWM0 channels 0, 1, 2, 3, 4, 8 and 9 on 7, 32, 36, 33, 37, 35 and 40. Standby PWM0-2 uses PL4 (28). |
| Резервы | Explicitly release or restore the camera or pin-test device. A conflicting SPI/UART/PWM request leaves these devices in place. |

The package uses the existing boot lock and an A733-specific undo journal
(`/boot/armbianEnv.txt.a733-panel-backups`). The check below runs with a private
boot tree and emulated sysfs built from the distribution DTB. Supply the extracted
package prefix as a third argument to exercise its assembled shell modules.
Set `PANEL_TEST_CHROMIUM` to a Chromium executable for the loopback browser test.

```sh
python3 tests/hardware/check-a733-panel.py "$A733_ALLWINNER_DTB_DIR" "$GUI_CHECKOUT"
```
