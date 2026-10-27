# Zero 2W hardware and radio ecosystem

Design checkpoint, 2026-10-27. The user confirmed a **SPI Waveshare SX1262
433 MHz HAT with GNSS** and identified **markqvist/Reticulum** as the requested
project. The board is now powered off. No radio, GNSS, GPIO or modem trial was
performed for this checkpoint. Exact HAT revision and current bus routing still
need verification. This plan does not install services or enable transmission.

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

## Candidate HAT mapping

The official [Meshtastic Waveshare profile](https://github.com/meshtastic/firmware/blob/eaba8b95bebab04c4f13a27b63e000ebdc1e5fac/bin/config.d/lora-waveshare-sxxx.yaml)
uses Raspberry Pi BCM numbering. Translated to physical header positions and
the existing WiringPi Zero 2W map, it gives the following **candidate**, not an
instruction to drive pins before checking the actual HAT revision:

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
identifies the GNSS part as L76K with a default 9600-baud UART. Confirm the
schematic for this physical revision before applying the candidate mapping.
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
  pins by `core/resources.py`; they do not match the candidate HAT table.
- `sx1262_driver.py` starts at 868 MHz independently of configuration. It opens
  SPI 0.0 by default and does not implement the candidate pin-40 CS / pin-31
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

For one physical radio, offer **Off / Meshtastic / Reticulum / Diagnostics**.
Switching must stop the old owner, wait for release, acquire a shared lock,
start the chosen backend and verify health; failed activation restores the
previous configuration without creating two owners. Combine systemd conflicts,
device permissions and cooperative locking: spidev itself is not an exclusive
lock. Reticulum may keep running on LAN while Meshtastic owns the radio.
Simultaneous independent LoRa meshes require a second radio; automatic time
sharing and a Meshtastic–Reticulum message bridge are outside the first release.

GNSS needs one UART reader. Prefer a system GNSS provider such as gpsd and
consumer adapters; verify support in the selected meshtasticd version before
promising direct gpsd integration. If it requires exclusive serial access,
define a single owner or an explicit forwarding adapter. Battery data comes
from UPower/power_supply, never competing reads of the UPS MCU. Keep location
broadcasts and network bridges explicit configuration choices.

## Delivery order and completion evidence

1. Python GPIO binding and application migration: host tests, then real ownership,
   cleanup and event tests. No unsupported OPi.GPIO fallback.
2. Board/HAT profile and overlay manager: resolve controller and CS, validate
   resource conflicts, UART console migration and reversible boot changes.
3. SX1262/GNSS bring-up: bounded SPI status/BUSY/reset/IRQ checks, correct RF
   switch behavior, NMEA reception and real GNSS fix. Record exact hardware and
   software versions. FT232H captures can validate protocol/timing once attached.
4. Meshtastic: known-good peer exchange, long-message/CRC qualification, daemon
   restart/reboot recovery, client UI. Label this HAT's upstream limitation.
5. Reticulum: LAN service first, then SPI adapter and independent peer exchange,
   boundary-size packets, interruption/recovery and verified radio ownership.
6. Ecosystem acceptance: UPS remains visible, GNSS has no competing reader,
   switching radio services releases all resources, overlay rollback preserves
   unrelated settings, and status distinguishes absence/failure from simulation.

No implementation of the new radio or Python binding is claimed by this plan.
The next executable work is step 1; GPIO tests on the powered-off board wait.
