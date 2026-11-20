# Orange Pi Zero 2W backlog

Stable numbering from the last numbered task list in the project conversation.
Updated 2026-11-20. Earlier lists used different numbering; use these names with
numbers when discussing work. Browser checkpoint: `9d0a7ede` on
`codex/display-controls`; its remaining limitations are retained separately.

| ID | Scope | Remaining acceptance |
|---|---|---|
| 1 | SPI/I2C and overlays | Enable and verify the intended controllers on this image; real exchange with devices |
| 2 | Shared pin map | Resolve CC1101/nRF24 chip-select and LoRa-reset/nRF24-CE conflicts |
| 3 | Python GPIO | Checked GPIO/events/PWM1 binding and ownership UIs implemented. [Offline verification and two board tests](zero2w-python-gpio.md). [Waveshare SX1262 migrated and ARM64-tested](https://github.com/shipmarty43/armbian-gui/blob/cfe82a273301374e464aeaf0941305fb0611c199/docs/hardware/SX1262.md). Board loopback, RF peer exchange and other OPi.GPIO consumers remain |
| 4 | DFR0528 power board | **Complete in the user-accepted scope (2026-10-27):** battery telemetry, kernel/UPower integration, overlay manager and reboot persistence. MAX17043 charging-status limitation retained; [acceptance boundary](zero2w-radio-ecosystem.md#accepted-ups-baseline) |
| 5 | Attached hardware modules | Waveshare SX1262 433 MHz passed [on-board SPI, RX timeout and native HAL checks](zero2w-radio-board-2026-11-20.md). The [LoRaWAN Class A stack](../../hardware/lorawan/README.md) still needs gateway acceptance. [L76K → gpsd → opi-gnss](zero2w-console-tty.md#gpsd-and-opi-gnss-on-the-board) delivered live receiver data on UART0. A satellite fix and live failover between L76K and SIM7600G-H remain for the [dual-source GNSS provider](../../hardware/gnss/README.md). [Meshtastic direct texts, node selection and ACKs in the TUI](../../hardware/mesh/README.md#two-simulator-menu-check) passed on two simulators. [Reticulum delivery over a two-host LAN](../../hardware/mesh/README.md#two-physical-hosts-over-lan) passed. [Signed LXMF delivery and inbox verification](../../hardware/mesh/README.md#signed-lxmf-messages-over-lan) passed in both directions after client restart. [LXMF inbox, contact selection and sending from the configurator](../../hardware/mesh/README.md#mailbox-acceptance-through-the-configurator) passed over LAN. [SX1262 owner selection, rollback and crash recovery](../../hardware/sx1262-mode/README.md) passed in the no-radio profile. The [Meshtastic hardware profile](../../hardware/meshtastic-sx1262/README.md) passed native ARM64 parser, modeled RX/IRQ and TX-inhibit tests. The [sealed RNode-compatible Reticulum RX adapter and shared SPI clock menu](../../hardware/reticulum-sx1262/README.md) passed software interoperability and ARM64 I/O tests. [SX1262 diagnostics, RNode RSSI/SNR and error counters](../../hardware/reticulum-sx1262/README.md#sx1262-diagnostics-and-rnode-signal-quality) passed on the no-radio double. Physical RF qualification, RNode hardware peer testing, PN532, CC1101 and nRF24 remain in the [acceptance plan](zero2w-radio-ecosystem.md). |
| **6** | **WiringPi API completeness** | PWM1 public API, SPI descriptor cleanup and serial API fixes implemented in the controls follow-up. Other pins/channels, I2C/SPI/UART hardware exchange and timing with external equipment remain |
| **7** | **armbian-config fork** | Native CPUFreq boot defaults and rollback tested. Profile across login and operator-observed hotplug checked; profile across reboot, continuous hotplug capture and switching distinct display managers remain |
| 8 | GPU, video and desktop | Retain the browser checkpoint; color fix, CMA, long/adaptive playback, audio, floating-point compute and games remain |
| 9 | Native CVBS | [DRM route, stock DTB, DE33 colour and diagnostic kernel](../../hardware/cvbs/README.md) tested offline. Cold boot on Zero 2W, Android reference and Armbian PAL/NTSC captures with EasyCAP, then HDMI recovery remain |
| 10 | Web UI and release | Real device data, authentication/access control, integration, install/update/rollback and branch consolidation |
| 11 | USB host/device | [USB0 boot role module](zero2w-usb-role.md) added and tested locally; board off. Verify UPS/VBUS/cabling, both roles, USB1 modem/hub continuity, and separate gadget functions |
| 12 | Mobile modem | [MM/NM profile controls](zero2w-modem.md) and [GNSS capability discovery](../../hardware/gnss/README.md) implemented. For SIM7600G-H / Kyivstar, verify USB composition, SIM, routes/DNS, reconnection, autoconnect on USB1 and GNSS on hardware when modem trials resume. |
| 13 | Orange Pi Zero 3W / A733 port | [SoC manuals, board schematics, header comparison and ordered port tasks](zero3w-port.md). Schematic-level assessment complete. Target board profile, overlays and hardware acceptance pending. |

Current accepted wiring: physical **32 ↔ 29 through 1 kOhm**, with stock
`pwm1-pi11`. Older 37 ↔ 29 tests must not be rerun on this connection. FT232H is
not attached. Hardware encoding is not demonstrated by the tested decoder stack.

Follow evidence in [the hardware index](README.md) and
[the controls follow-up](zero2w-controls-2026-10-27.md). A successful API unit test,
requested sysfs value and measured electrical signal are distinct evidence.
