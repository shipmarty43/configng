# Orange Pi Zero 2W backlog

Stable numbering from the last numbered task list in the project conversation.
Updated 2026-10-31. Earlier lists used different numbering; use these names with
numbers when discussing work. Browser checkpoint: `9d0a7ede` on
`codex/display-controls`; its remaining limitations are retained separately.

| ID | Scope | Remaining acceptance |
|---|---|---|
| 1 | SPI/I2C and overlays | Enable and verify the intended controllers on this image; real exchange with devices |
| 2 | Shared pin map | Resolve CC1101/nRF24 chip-select and LoRa-reset/nRF24-CE conflicts |
| 3 | Python GPIO | Next foundation: checked Python binding to the validated H618 backend, then migrate OPi.GPIO consumers; [ecosystem plan](zero2w-radio-ecosystem.md) |
| 4 | DFR0528 power board | **Complete in the user-accepted scope (2026-10-27):** battery telemetry, kernel/UPower integration, overlay manager and reboot persistence. MAX17043 charging-status limitation retained; [acceptance boundary](zero2w-radio-ecosystem.md#accepted-ups-baseline) |
| 5 | Attached hardware modules | Direct-mounted Waveshare SPI SX1262 433 MHz + L76K GNSS (standard shield pinout): [LoRaWAN Class A software](../../hardware/lorawan/README.md) implemented, host-tested only; board/gateway acceptance, official Meshtastic and Reticulum adapters remain. [Ordered acceptance plan](zero2w-radio-ecosystem.md). [Dual GNSS source selection](zero2w-radio-ecosystem.md#two-gnss-sources) for L76K and SIM7600G-H remains to implement and qualify. PN532, CC1101 and nRF24 tests remain |
| **6** | **WiringPi API completeness** | PWM1 public API, SPI descriptor cleanup and serial API fixes implemented in the controls follow-up. Other pins/channels, I2C/SPI/UART hardware exchange and timing with external equipment remain |
| **7** | **armbian-config fork** | Native CPUFreq boot defaults and rollback tested. Profile across login and operator-observed hotplug checked; profile across reboot, continuous hotplug capture and switching distinct display managers remain |
| 8 | GPU, video and desktop | Retain the browser checkpoint; color fix, CMA, long/adaptive playback, audio, floating-point compute and games remain |
| 9 | Native CVBS | Android reference capture; DRM/kernel/DT bring-up and PAL/NTSC capture with EasyCAP |
| 10 | Web UI and release | Real device data, authentication/access control, integration, install/update/rollback and branch consolidation |
| 11 | USB host/device | [USB0 boot role module](zero2w-usb-role.md) added and tested locally; board off. Verify UPS/VBUS/cabling, both roles, USB1 modem/hub continuity, and separate gadget functions |
| 12 | Mobile modem | [MM/NM profile controls](zero2w-modem.md) added; SIM7600G-H / Kyivstar identified, initial APN internet; verify USB driver/composition, SIM, routes/DNS, reconnection and autoconnect on USB1. Add GNSS capability discovery and the shared location adapter; hardware modem trials remain deferred |

Current accepted wiring: physical **32 ↔ 29 through 1 kOhm**, with stock
`pwm1-pi11`. Older 37 ↔ 29 tests must not be rerun on this connection. FT232H is
not attached. Hardware encoding is not demonstrated by the tested decoder stack.

Follow evidence in [the hardware index](README.md) and
[the controls follow-up](zero2w-controls-2026-10-27.md). A successful API unit test,
requested sysfs value and measured electrical signal are distinct evidence.
