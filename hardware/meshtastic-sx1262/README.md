# Waveshare SX1262 433/470M GNSS HAT on Orange Pi Zero 2W

**System → Hardware → SX1262 mode → Check Meshtastic hardware profile (read only)** validates the live Armbian routing, installed firmware digest and stored preferences. It works with the selector in `no-radio` and `Off`. The same check is available through `sudo armbian-config-zero2w --api module_sx1262_mode check-meshtastic`.

## Wiring and firmware inputs

The renderer resolves the spidev entry by its live device-tree node and resolves the main GPIO controller through `/sys/bus/gpio/devices/gpiochip*/of_node`. It verifies the H618 Zero 2W compatible, main PIO layout, SPI1 pinmux, single active-low CS0 on PI3, endpoint binding and device clock ceiling. The selected SPI rate comes from the [shared clock control](../reticulum-sx1262/README.md#two-separate-clocks). The on-board run resolved `spidev1.0` and `gpiochip1`. The SX1262 SPI HAL and Arduino GPIO mapping in the pinned native firmware accept separate Portduino IDs and chip-relative line offsets. [Firmware GPIO parser](https://github.com/meshtastic/firmware/blob/54e0d8d/src/platform/portduino/PortduinoGlue.cpp) · [Portduino SPI implementation](https://github.com/meshtastic/framework-portduino/blob/5f100db1b33fb0c23f149fd47c9779abcfe1e09d/cores/portduino/linux/LinuxHardwareSPI.cpp)

| HAT signal | Physical pin | H618 routing | Meshtastic setting |
|---|---:|---|---|
| MOSI / MISO / SCLK | 19 / 21 / 23 | PH7 / PH8 / PH6 | SPI1, mode 0, 2 MHz |
| NSS | 40 | PI3 | Kernel CS0 via the overlay; omit `Lora.CS` so firmware makes no GPIO claim |
| Reset | 12 | PI1, offset 257 | `Reset` |
| DIO1 | 36 | PC12, offset 76 | `IRQ` |
| BUSY | 38 | PI4, offset 260 | `Busy` |
| External RF switch | 31 | PI15, offset 271 | `RXen`, high in RX, low in idle/TX |

The radio uses its crystal, with DIO3 TCXO voltage zero and internal DIO2 RF switching enabled. The upstream Waveshare sample uses `SX126X_ANT_SW`, which this firmware holds high. The HAT's documented switching sequence calls for the `RXen` mapping above. The YAML leaves GPS, I²C, UDP and extra config directories unused. [Manufacturer demo and prior board results](../../tests/hardware/zero2w-radio-ecosystem.md#direct-spi-hat-driver-2026-11-20) · [Native switch handling](https://github.com/meshtastic/firmware/blob/54e0d8d/src/mesh/SX126xInterface.cpp) · [RadioLib RF switch table](https://github.com/jgromes/RadioLib/blob/7.6.0/src/Module.cpp)

The separate version-24 firmware preferences select **EU_433, LONG_FAST, CLIENT_MUTE and tx_enabled=false** with default channel selection and no frequency overrides. Frequency readback on the software double was **433.875 MHz**. Setting a previously unset region through the native admin API can turn TX on. The preparation tool edits the saved configuration offline, clears the simulator security section and validates a copy by booting it in forced simulation. Only the new `prefs/config.proto` is promoted. The setup preserves existing valid hardware preferences and refuses incompatible ones. [Upstream region transition](https://github.com/meshtastic/firmware/blob/54e0d8d/src/modules/AdminModule.cpp) · [Upstream HAT limitations](https://meshtastic.org/docs/meshtasticd/hardware/)

## Sealed installation and selector contract

Use the pinned ARM64 Ubuntu build and Python environment from the [mesh installation](../mesh/README.md#install-on-an-arm64-zero-2w-running-ubuntu-2604). The executable digest is `2b37b97948ebd9a75f22d52f653ce4977b6b6be9afdb7c5c02a973bd34e15653`. Install this fork's assembled configurator as usual, then the optional files:

```sh
sudo install -m644 share/armbian-config/sx1262_spi.py /opt/opi-mesh/
sudo install -m644 hardware/meshtastic-sx1262/{sx1262_profile.py,qualify_sx1262_profile.py,zero2w-waveshare.yaml.in} /opt/opi-mesh/
sudo install -m644 hardware/meshtastic-sx1262/opi-meshtastic-radio.service /usr/local/lib/systemd/system/
sudo systemctl daemon-reload
```

On the board, run the following preparation and acceptance steps with Bash. The build used a 160 MiB cgroup limit and one native firmware process at a time.

```sh
sealed=(--quiet --wait --collect --pipe -p PrivateDevices=yes -p DevicePolicy=closed
        -p PrivateNetwork=yes -p PrivateTmp=yes -p CapabilityBoundingSet=
        -p ProtectSystem=strict -p ProtectKernelTunables=yes -p ProtectHome=yes
        -p NoNewPrivileges=yes -p LimitCORE=0 -p UMask=0077 -p MemoryMax=160M
        -p TasksMax=48 -p RuntimeMaxSec=90)
sudo systemd-run "${sealed[@]}" -p StateDirectory=opi-meshtastic-radio -p StateDirectoryMode=0700 \
    /opt/opi-mesh/venv/bin/python /opt/opi-mesh/qualify_sx1262_profile.py seed
sudo systemd-run "${sealed[@]}" /opt/opi-mesh/venv/bin/python /opt/opi-mesh/qualify_sx1262_profile.py native-check
sudo armbian-config-zero2w --api module_sx1262_mode check-meshtastic
```

`opi-meshtastic-radio.service` has a private device namespace, closed device policy, private network and no boot enablement. The installation provides **no device bindings**. Hardware activation requires both the hardware selector profile and a matching site-specific systemd device drop-in. The default installation leaves this drop-in absent. `sx1262_profile.py device-policy` only prints the expected bindings for later review. The selector runs Meshtastic preflight before releasing the current owner; it rejects unavailable access or invalid preferences. Direct unit activation also has a systemd condition and the same launch-time checks. Keep the existing simulator mailbox and GNSS services separate from this hardware instance.

For a future qualified installation, the launcher checks the namespace-visible character device numbers against sysfs, holds `/run/lock/opi-radio.lock` across exec and uses a private firmware state directory. The unit's post-start check requires the expected phone API identity, firmware and TX-disabled configuration. Native SX1262 initialization precedes phone API startup in this build. A failed startup returns to the selector's [rollback logic](../sx1262-mode/README.md). Physical device access is required for a later bench trial and was omitted throughout this qualification.

## Software-only acceptance on Zero 2W, 2026-11-20

| Check | Result |
|---|---|
| Live metadata | Validated DT and sysfs without opening spidev or claiming GPIO. Main PIO had 288 lines and the kernel reported `spi1 CS0` on PI3. |
| Firmware parser | The installed ARM64 executable parsed the generated YAML using `--output-yaml` in an empty private device namespace. The four GPIO bindings and SPI endpoint survived the round trip. A full native start with no devices failed in `LinuxGPIOPin::getLine` at the first GPIO. |
| Hardware path on a software double | The native binary requested offsets 76, 260, 257 and 271. The SPI fixture accepted mode 0, MSB first, 2 MHz and one transfer per message with ordinary kernel CS framing. It observed a reset pulse, DIO2 switch enable, RXen high at SetRx and the expected frequency word. |
| Interrupt handling | A synthetic DIO1 with RX_DONE and CRC_ERR produced an IRQ status read, flag clear and return to RX. |
| TX inhibition | A synthetic Phone API text produced a queue result of 34 (`ERRNO_DISABLED`) with the same packet ID. The double rejects SetTx, continuous wave and infinite preamble. No such command occurred. |
| Lifecycle | The native executable retained the launcher's PID and exclusive test flock. The service readiness probe passed on the double, and a new process could acquire the test lock after stop. |
| Installed selector | The check was exercised in the real SXMD01 TUI. Hardware preflight rejected activation, the physical backend stayed inactive, and the saved and live mode were Off in the no-radio profile. |

The test-only C library never forwards an ioctl. It requires ordinary files at both substituted device paths. The driver script checks the private loopback namespace, the absence of other hardware devices and the file types before executing firmware. Test data and generated logs are confined to temporary directories. To repeat the GPIO/SPI test from a checkout with a C compiler and libgpiod v2 development headers:

```sh
sudo bash hardware/meshtastic-sx1262/tests/run-fake.sh
/opt/opi-mesh/venv/bin/python hardware/meshtastic-sx1262/tests/test_profile.py
```

The remaining physical checks are NSS and RF-switch timing on the board, BUSY/IRQ electrical behaviour, RF frequency, reception sensitivity and actual packet reception. The software tests provide no measurement of radiated power or assurance of TX inhibition on a physically connected running backend.
