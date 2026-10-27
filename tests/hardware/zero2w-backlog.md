# Orange Pi Zero 2W backlog

Stable numbering from the last numbered task list in the project conversation.
Updated 2026-10-27. Earlier lists used different numbering; use these names with
numbers when discussing work. Browser checkpoint: `9d0a7ede` on
`codex/display-controls`; its remaining limitations are retained separately.

| ID | Scope | Remaining acceptance |
|---|---|---|
| 1 | SPI/I2C and overlays | Enable and verify the intended controllers on this image; real exchange with devices |
| 2 | Shared pin map | Resolve CC1101/nRF24 chip-select and LoRa-reset/nRF24-CE conflicts |
| 3 | Python GPIO | Connect the validated H618 backend to armbian-gui; C WiringPi does not replace OPi.GPIO automatically |
| 4 | DFR0528 power board | Real adapter, identity, battery readings, unplug behavior and orderly shutdown |
| 5 | Attached hardware modules | Individual PN532, CC1101, nRF24, SX1262 and GPS protocol/device tests |
| **6** | **WiringPi API completeness** | PWM1 public API, SPI descriptor cleanup and serial API fixes implemented in the controls follow-up. Other pins/channels, I2C/SPI/UART hardware exchange and timing with external equipment remain |
| **7** | **armbian-config fork** | Native CPUFreq boot defaults and rollback tested. Profile across login and operator-observed hotplug checked; profile across reboot, continuous hotplug capture and switching distinct display managers remain |
| 8 | GPU, video and desktop | Retain the browser checkpoint; color fix, CMA, long/adaptive playback, audio, floating-point compute and games remain |
| 9 | Native CVBS | Android reference capture; DRM/kernel/DT bring-up and PAL/NTSC capture with EasyCAP |
| 10 | Web UI and release | Real device data, authentication/access control, integration, install/update/rollback and branch consolidation |

Current accepted wiring: physical **32 ↔ 29 through 1 kOhm**, with stock
`pwm1-pi11`. Older 37 ↔ 29 tests must not be rerun on this connection. FT232H is
not attached. Hardware encoding is not demonstrated by the tested decoder stack.

Follow evidence in [the hardware index](README.md) and
[the controls follow-up](zero2w-controls-2026-10-27.md). A successful API unit test,
requested sysfs value and measured electrical signal are distinct evidence.
