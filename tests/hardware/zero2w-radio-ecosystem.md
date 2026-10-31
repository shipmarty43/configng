# Zero 2W hardware and radio ecosystem

Design checkpoint, 2026-10-27; hardware clarification, 2026-10-31. The user confirmed a **SPI Waveshare SX1262
433 MHz HAT with GNSS** and identified **markqvist/Reticulum** as the requested
project. The board is now powered off. No radio, GNSS, GPIO or modem trial was
performed for this checkpoint. The user confirmed that the Waveshare is mounted
directly as a 40-pin shield using its standard pinout. There are two GNSS
sources: the HAT and the SIM7600G-H modem. Linux bus routing and physical
operation still need verification. This plan does not install services or
enable transmission.

## Accepted UPS baseline

DFR0528 support is **complete in the user-accepted scope**: MCU identification,
voltage/percentage, Linux `power_supply`, UPower integration, XFCE percentage
configuration, boot overlay and configurator controls with dependency checks
and rollback. Keep the [hardware evidence](zero2w-ups-2026-10-27.md) and
[overlay-manager evidence](zero2w-ups-overlay-manager.md) as the test record.

MAX17043 has no charging-status flag; the documented DFR0528 MCU interface does
not supply one either. Keep `Unknown`, with no extra GPIO and no trend-based
inference. UPower's aggregate heuristic is not a hardware charging measurement.
Visual desktop observation, load/switchover and orderly shutdown were not
qualified. They are outside this accepted scope, not prerequisites for moving
on to the radio work. Packaging for other kernels remains a release concern.

## Responsibilities

| Layer | Responsibility | Boundary |
|---|---|---|
| Kernel and DT | GPIO ownership, SPI/UART pinmux, I2C UPS, PWM | No userspace MMIO pinmux; no duplicate driver for a bound device |
| WiringPi H618 backend | Verified header mapping, GPIO requests/events, supported PWM | Reuse its discovery and error handling from Python |
| configng hardware modules | Board/HAT profile, dependency/conflict checks, generated service settings, transactional apply/rollback | Separate module files; keep radio protocols outside shell code |
| System services | `meshtasticd`, `rnsd`, GNSS provider, UPower | A single owner of each radio and UART; ordinary application APIs |
| armbian-gui | Status, messages and user interaction | Client of services; do not reopen the radio behind a daemon |

Use a versioned hardware profile as the shared input to overlay validation and
service configuration. It must describe physical pins, SoC signals, controller
identity, required mux, RF variant and resource claims. Resolve Linux device
numbers from the running system; do not encode `/dev/gpiochip0`, `/dev/i2c-1` or
`/dev/spidev0.0` as universal board facts. The WiringPi board map remains the
authority for physical-to-SoC GPIO translation; test profile mappings against it.
Keep profile data separate from credentials, radio identity and channel keys.

Extend the existing overlay manager rather than creating another boot-file
writer. A future HAT module must use the same lock, composed-DT validation,
backup and rollback rules as the UPS module. Distinguish requested next-boot
configuration, loaded hardware, running service and tested connectivity.

## Standard shield mapping

The official [Meshtastic Waveshare profile](https://github.com/meshtastic/firmware/blob/eaba8b95bebab04c4f13a27b63e000ebdc1e5fac/bin/config.d/lora-waveshare-sxxx.yaml)
uses Raspberry Pi BCM numbering. Translated to physical header positions and
the existing WiringPi Zero 2W map, it gives the standard shield profile below.
The user confirmed direct mounting, so no custom wire assignment is needed.
This documents the intended wiring; it does not establish working kernel pinmux:

| Signal | Physical pin | Zero 2W SoC signal | Note |
|---|---:|---|---|
| SPI MOSI | 19 | PH7 | Header SPI controller, not an assumed Linux bus number |
| SPI MISO | 21 | PH8 | Shared bus data |
| SPI SCLK | 23 | PH6 | Shared bus clock |
| Radio CS | 40 | PI3 | Upstream BCM21; not the usual header CS0 at pin 24 |
| Radio RESET | 12 | PI1 | Upstream BCM18 |
| Radio DIO1 / IRQ | 36 | PC12 | Upstream BCM16 |
| Radio BUSY | 38 | PI4 | Upstream BCM20 |
| Antenna switch / TX enable | 31 | PI15 | Upstream `SX126X_ANT_SW`, BCM6 |
| Host UART TX → GNSS RX | 8 | PH0 | Verify UART routing and console ownership |
| Host UART RX ← GNSS TX | 10 | PH1 | GNSS is separate from the SPI radio |

The [manufacturer product](https://www.waveshare.com/product/raspberry-pi/sx1262-lorawan-hat.htm)
identifies the GNSS part as L76K with a default 9600-baud UART. Use the
manufacturer shield wiring, then verify the SPI/UART routing on the installed OS.
DFR0528 uses physical 3/5, so this map has no direct signal-pin overlap with its
I2C connection. Stack clearance, shared supply loading and other attached HATs
still need checking. The current PWM test resistor at 32–29 is separate.

CS handling is a specific bring-up gate: choose one verified method, either a
DT-controlled GPIO chip select on pin 40 or daemon-controlled CS with the SPI
transfer configured accordingly. Do not let both the kernel and daemon own PI3.
Do not select a spidev node belonging to SPI flash. UART use must not compete
with a login console or kernel console; any console removal needs rollback.
Do not copy TCXO voltage or RF-switch settings from a different SX1262 module.

## Existing application audit

Inspected `armbian-gui` revision `caa06d88313cddedd15ace4aa8c67c7b06c8a37b`:

- `config/main.yaml` enables LoRa with 868 MHz / `EU_868`, inconsistent with the
  user's 433 MHz hardware. RESET/BUSY/DIO1 values 18/24/23 are consumed as BOARD
  pins by `core/resources.py`; they do not match the standard HAT table.
- `sx1262_driver.py` starts at 868 MHz independently of configuration. It opens
  SPI 0.0 by default and does not implement the standard pin-40 CS / pin-31
  antenna-switch arrangement. Merely changing the frequency field is insufficient.
- `meshtastic_protocol.py` uses its own `struct.pack` layout and byte-sum
  checksum. This is not the official Meshtastic protobuf/radio implementation.
  `lora_module.py` sends these packets directly through the local SX1262 driver.
- `RNS.Reticulum()` is instantiated, but there is no connection from that
  instance to this SX1262 driver. A running Reticulum instance or importable
  package does not demonstrate a working LoRa interface.
- OPi.GPIO consumers still lack a verified Zero 2W Python backend. In-process
  `GpioLease` ownership helps cleanup but cannot correct a wrong board map.

These are source findings, not new observations on the board. During migration,
remove the automatic local protocol path from the production workflow and keep
any raw-radio experiments explicitly separate. Do not copy application code
under its custom license into the independently licensed system components.

## Python GPIO first

Build a small, separately packaged Python binding in the WiringPi fork, then
use it from `armbian-gui`. Do not revive a second H618 register map inside
OPi.GPIO or shell out once per GPIO write: ownership must persist in-process.

First API: context-managed line requests, physical pin numbering, input/output,
initial output level, read/write, bias and deterministic release. Validate the
board and library capabilities before touching a line. Expose checked C entry
points where the legacy void API cannot reliably report failure; map errors to
Python exceptions. Initial output value must be part of the kernel request, not
an unsafe setup-then-write pulse. Do not bind private C symbols as a stable ABI.

Then add edge events/waits and the already qualified PWM1 capabilities. Keep
callback lifetime, cancellation, error propagation and interpreter shutdown
explicit. Do not advertise all OPi.GPIO compatibility before implementing it.
Migrate CC1101/nRF24/other direct drivers through a small application adapter;
Meshtastic clients should not need GPIO access at all.

Acceptance: wrong-board and power-pin rejection, conflicting owners, failed
request cleanup, initial-level behavior, per-line release, process exit and
event cancellation. Run host failure tests first; repeat real loopback only with
the appropriate confirmed wiring. Existing C tests do not prove Python behavior.

## Meshtastic and Reticulum

Use official **meshtasticd** for SPI radio ownership and the official Python
client for application messages. Generate a Zero 2W-specific profile using
verified gpiochip/line discovery. Pin the daemon/config schema versions together.
Treat the 433 MHz hardware variant, selected region, modem preset and power
settings as validated inputs; do not retain the 868 MHz defaults.

Upstream marks the [Waveshare profile](https://github.com/meshtastic/firmware/blob/eaba8b95bebab04c4f13a27b63e000ebdc1e5fac/bin/config.d/lora-waveshare-sxxx.yaml)
`deprecated`. Its [hardware guidance](https://meshtastic.org/docs/meshtasticd/hardware/)
reports limitations with longer messages and recommends `CLIENT_MUTE` if using
this HAT. Start qualification in that role; test short and long payloads,
different airtimes and CRC failures with a known-good peer. Do not claim the
hardware problem is fixed by GPIO work or assume the exact cause on this unit.
`CLIENT_MUTE` prevents relaying; it is not a receive-only/transmit-disable switch.

For **Reticulum**, first integrate the ordinary `rnsd` service and local status
on an explicitly configured LAN interface. Keep that milestone separate from
radio support. The [official interface documentation](https://reticulum.network/manual/interfaces.html)
provides RNode, KISS, Pipe and custom interfaces; the standard RNode path talks
to an RNode transport, not directly to `/dev/spidev*`.

The SPI HAT therefore needs a qualified Linux radio adapter. Evaluate existing
maintained adapters before writing one. Preferred radio acceptance target:
interoperate with an actual RNode, including its packet framing, fragmentation,
MTU, flow control and airtime behavior. A custom PipeInterface is an alternative
integration boundary, but two copies of our own adapter exchanging bytes would
not prove RNode interoperability. Never report “Reticulum over LoRa ready” from
the LAN service milestone alone. LXMF can follow as the messaging application.

For one physical radio, offer **Off / Meshtastic / Reticulum / LoRaWAN / Diagnostics**.
Switching must stop the old owner, wait for release, acquire a shared lock,
start the chosen backend and verify health; failed activation restores the
previous configuration without creating two owners. Combine systemd conflicts,
device permissions and cooperative locking: spidev itself is not an exclusive
lock. Reticulum may keep running on LAN while Meshtastic owns the radio.
Simultaneous independent LoRa meshes require a second radio; automatic time
sharing and a Meshtastic–Reticulum message bridge are outside the first release.

## Two GNSS sources

User-confirmed inventory, 2026-10-31. The shared provider and selection controls
below are planned, not implemented or hardware-tested.

| Source | Host connection | Planned owner / adapter |
|---|---|---|
| Waveshare L76K | Header UART, physical 8/10, default 9600 baud | One serial reader, preferably gpsd; resolve the actual UART and console conflict |
| SIM7600G-H GNSS | Modem USB connection on USB1 | ModemManager location adapter, subject to detected GPS capabilities |

The [ModemManager Location API](https://www.freedesktop.org/software/ModemManager/doc/latest/ModemManager/gdbus-org.freedesktop.ModemManager1.Modem.Location.html)
exposes supported/enabled sources and GPS raw/NMEA results. Discover capabilities
on this modem before selecting an adapter; do not hardcode a ttyUSB number or
open a competing AT session. Preserve existing location-source settings and
location-signal policy when enabling GNSS. Cellular registration or a working
data connection is not evidence of a GNSS fix. Modem trials remain deferred at
the user's request.

Planned common interface and configurator acceptance:

- Offer **Auto / Waveshare / Modem / Off**, with configurable priority in Auto.
  Manual selection must not silently substitute another receiver.
- Keep separate source status: absent, disabled, acquiring, valid fix, stale or
  error. Publish source identity, fix timestamp, age and available quality data;
  distinguish unavailable accuracy/satellite fields from measured zero.
- Auto chooses only a fresh, valid fix, falls back when it becomes unusable, and
  uses recovery hysteresis to prevent repeated switching. Define and test age
  and recovery thresholds. Never present an old coordinate as a current fix or
  average two receivers' coordinates without a separate fusion design.
- Keep one owner per physical interface. The two receivers can operate
  independently; switching the SX1262 radio backend must not reset GNSS.
- Expose the selected fix and each source's health to application clients.
  Verify the selected meshtasticd version's supported location input before
  promising direct gpsd integration; use an explicit adapter where required.
- Test missing devices, no fix, stale NMEA, USB reconnect, service restart and
  source recovery on the host first, then qualify each receiver and failover on
  the board. Confirm modem GNSS does not disrupt mobile data or USB1 devices.

Battery data comes from UPower/power_supply, never competing reads of the UPS
MCU. Keep location broadcasts and network bridges explicit configuration choices.

## Delivery order and completion evidence

1. Python GPIO binding and application migration: host tests, then real ownership,
   cleanup and event tests. No unsupported OPi.GPIO fallback.
2. Board/HAT profile and overlay manager: resolve controller and CS, validate
   resource conflicts, UART console migration and reversible boot changes.
3. SX1262/GNSS bring-up: bounded SPI status/BUSY/reset/IRQ checks, correct RF
   switch behavior, NMEA reception and real GNSS fix from each source. Record exact hardware and
   software versions. FT232H captures can validate protocol/timing once attached.
4. Meshtastic: known-good peer exchange, long-message/CRC qualification, daemon
   restart/reboot recovery, client UI. Label this HAT's upstream limitation.
5. Reticulum: LAN service first, then SPI adapter and independent peer exchange,
   boundary-size packets, interruption/recovery and verified radio ownership.
6. Ecosystem acceptance: UPS remains visible, both GNSS sources have a single
   owner per interface and source selection rejects stale fixes,
   switching radio services releases all resources, overlay rollback preserves
   unrelated settings, and status distinguishes absence/failure from simulation.

## LoRaWAN software follow-up

The user subsequently requested the LoRaWAN software implementation. The
[optional native component](../../hardware/lorawan/README.md) now implements
EU433 Class A / OTAA-1.0.4 using pinned RadioLib and the existing H618 WiringPi
backend, private configuration, persistent nonces/session with write-ahead
recovery, exclusive radio ownership and configurator service controls. It is
disabled by default and has only host validation so far. This is an end device;
a matching gateway/server is required for network acceptance.

Python GPIO, Meshtastic/Reticulum adapters, the HAT overlay and physical radio
acceptance remain separate work. No implementation of those is claimed here.
