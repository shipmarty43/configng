# Experimental Zero 2W LoRaWAN node

Software implementation for the Waveshare **SPI SX1262 433 MHz/GNSS HAT**,
Orange Pi Zero 2W and the H618 WiringPi fork. **Not yet tested on the board or
against a gateway.** The board was powered off during this implementation.
This is an end-device service, not a LoRaWAN gateway or network server.

## Implemented contract

- EU433, LoRaWAN 1.0.4 **OTAA, Class A**, using RadioLib's MAC, crypto, ADR,
  duty-cycle controls and RX1/RX2 implementation. No replacement packet format.
- Separate native `opi-lorawan` process and optional systemd unit. Configuration
  and credentials are separate private files; keys never enter command arguments.
- Periodic fixed 1–32-byte payload, FPort 1–223, optional confirmed uplinks;
  received payloads and return codes go to the journal. GPS/battery telemetry
  encoders and automatic downlink command execution are not part of v0.1.
- Persistent nonces and session, identity binding, atomic replacement and fsync,
  state lock, write-ahead reservation and conservative crash recovery.
- `armbian-config` menu/API for checking, status, start and stop. Installation,
  provisioning and hardware verification are separate explicit steps. No boot
  overlays or automatic service enablement are changed by this component.

Class B/C, ABP, LoRaWAN 1.1, other bands, ChirpStack installation and a generic
Python GPIO package are not implemented here. The native HAL already reuses the
validated WiringPi GPIO mapping; this does not complete the Python binding work.

## Dependencies and build

The application is GPL-3.0-or-later. RadioLib is used as an external dependency,
not copied into the configurator. Its MIT license and WiringPi's LGPL license
remain applicable when distributing binaries/libraries.

Use [RadioLib revision 3b1d917](https://github.com/jgromes/RadioLib/tree/3b1d917bbacba0062dd7064c1157893ef9c6384e)
and [WiringPi H618 revision f627770](https://github.com/shipmarty43/WiringPi/tree/f627770e5a0ae10331e39ef5694ee3928b136897).
The build rejects a different or dirty RadioLib tree because nonce
reservation depends on its protected state layout. There are no build-time
downloads. Use a C++20 compiler, CMake, Git, OpenSSL development headers, and
Python 3 for CLI tests. On Debian/Ubuntu the general build prerequisites are
`build-essential cmake git libssl-dev python3`; build/install the specified
WiringPi fork separately and run its installation's library-cache update.

```sh
git clone https://github.com/jgromes/RadioLib.git /path/to/RadioLib
git -C /path/to/RadioLib checkout 3b1d917bbacba0062dd7064c1157893ef9c6384e
cmake -S hardware/lorawan -B /tmp/opi-lorawan-build \
  -DRADIOLIB_SOURCE_DIR=/path/to/RadioLib
cmake --build /tmp/opi-lorawan-build -j2
ctest --test-dir /tmp/opi-lorawan-build --output-on-failure
sudo cmake --install /tmp/opi-lorawan-build
sudo systemctl daemon-reload
```

Default install prefix is `/usr/local`, matching the provided unit. For a
development library outside the system paths, provide `WIRINGPI_INCLUDE_DIR`
and `WIRINGPI_LIBRARY`. Build on AArch64 for deployment; a host x86 binary is
only a host-test artifact. Do not run `systemctl enable` during installation.

## Configuration and fresh identity provisioning

```sh
sudo install -d -m 700 /etc/opi-lorawan /var/lib/opi-lorawan
sudo install -m 600 hardware/lorawan/lorawan.conf.example /etc/opi-lorawan/lorawan.conf
sudo install -m 600 hardware/lorawan/credentials.conf.example /etc/opi-lorawan/credentials.conf
```

Edit the two files locally. The credential placeholders deliberately fail
validation. Register a **fresh** device identity on the network server, select
LoRaWAN 1.0.4 / EU433, and enter JoinEUI, DevEUI and AppKey. EUIs are 16 hex
digits in displayed MSB-first order; AppKey is 32 hex digits. No byte reversal,
spaces or `0x` prefixes. Never commit the populated files.

The configuration parser accepts exactly the documented keys, no shell
expansion or sourced script. Both files must be owned by the executing user
with no group/other permissions. Production uses root; test fixtures use the
test user. The example leaves `enabled=false` and `wiring_verified=false`.

```sh
sudo opi-lorawan check /etc/opi-lorawan/lorawan.conf \
  /etc/opi-lorawan/credentials.conf /var/lib/opi-lorawan
sudo opi-lorawan provision /etc/opi-lorawan/lorawan.conf \
  /etc/opi-lorawan/credentials.conf /var/lib/opi-lorawan
```

`check` and `provision` do not open GPIO/SPI. Provisioning refuses an existing
state file, including a corrupt one. Missing/corrupt/incompatible state during
normal operation causes a hard failure, never automatic zero counters. If an
identity has already transmitted from another installation, do not provision it
as fresh here. Preserve its newest state or register a new identity. Restoring
an old SD backup with the same identity can roll back counters; the file checksum
cannot detect such a valid old copy. No counter-reset command is provided.

## Hardware activation gate

The fixed physical map is CS **40**, DIO1 **36**, RESET **12**, BUSY **38**,
TX/antenna switch **31**, SPI MOSI/MISO/CLK **19/21/23**. See the
[standard shield profile and source](../../tests/hardware/zero2w-radio-ecosystem.md).
The user confirmed direct 40-pin shield mounting. Kernel routing and resource
ownership still require verification before enabling it. The HAL requires both
Zero 2W and H618 DT compatibles and checks WiringPi's physical-to-SoC map.

The `spidev` path in the example is a placeholder. Verify its controller, mux,
and other users on the actual image. The kernel must allow `SPI_NO_CS`; PI3
(physical 40) is driven by userspace and must not also be a kernel chip select.
This is not suitable for arbitrary concurrent spidev clients. The profile uses
2 MHz mode 0, crystal operation (DIO3 TCXO voltage zero), DIO2 RF switch and the
additional pin-31 transmit switch. No device-tree overlay is installed yet.

Only after checking these assumptions and arranging a matching gateway should
both activation flags become true. Then use **System → Hardware → LoRaWAN node**
in the fork, or:

```sh
sudo armbian-config --api module_lorawan check
sudo armbian-config --api module_lorawan start
sudo armbian-config --api module_lorawan status
sudo journalctl -u opi-lorawan -f
sudo armbian-config --api module_lorawan stop
```

Use `armbian-config-zero2w` instead when using the isolated fork wrapper on the
test board. The menu appears only when `/usr/local/bin/opi-lorawan` is installed.
Start refuses an active known radio service rather than stopping it implicitly.
The unit also declares conflicts and the process holds `/run/lock/opi-radio.lock`.
Future Meshtastic/Reticulum launchers must participate in the same lock. Unmanaged
programs are not controlled by a cooperative lock; GPIO ownership still applies.
Reticulum on LAN can remain active while LoRaWAN owns the HAT.

## Persistence and timing

Before a join, the **next** DevNonce is committed to disk while RadioLib uses
the reserved current value. A failure consumes that nonce; exhaustion stops the
service instead of wrapping. Before any uplink, the durable session is removed
while its nonces remain. After a successful exchange, current counters, keys and
MAC state are saved together with their integrity digest. A crash in between
therefore forces a new OTAA session rather than reusing an uncertain frame count.
An ambiguous radio error also drops the live session before retrying.

The service requires a plausible wall clock, preserves a next-operation time
across boots, and writes a one-hour conservative holdoff before an exchange.
After success it uses the greater of the configured interval and RadioLib's
duty-cycle delay; after failure/interruption the holdoff remains conservative.
A backwards clock step extends the wait. A correct system clock is still an
operational prerequisite; the plausibility check is not proof of synchronization.

GPIO events are polled and callbacks dispatched on the same thread at yield
points, avoiding concurrent access to RadioLib's callback flags. Linux scheduling
and RX-window timing must be measured on the real board under load. This is not
a hard real-time guarantee. SIGTERM interrupts waits; unfinished exchanges keep
the conservative recovery record. Stop attempts standby and releases owned pins.

## Validation and remaining acceptance

Host tests exercise real RadioLib nonce/session serialization with synthetic
state (not a simulated successful join), failed restore, nonce exhaustion,
identity mismatch, file integrity, exclusive state ownership, atomic replacement,
child-process exit, permissions and symlink rejection. CLI tests cover checking,
provisioning, disabled-run refusal and rejection of existing/corrupt state.
HAL tests use link-time GPIO doubles for restricted pin access, request/read/write
failures, edge dispatch, cancellation and per-line cleanup; they do not exercise
kernel ioctls or physical timing.
The Bats tests in `tests/bats/lorawan.bats` check configurator service dispatch
and conflict refusal using mocks. A running service does not prove connectivity.

Still required on hardware: SPI/reset/BUSY/IRQ/RF-switch verification, OTAA join
against a real EU433 gateway/server, RX1/RX2 and confirmed acknowledgments,
ADR/channel changes, restart/power-loss tests and long-packet reliability. The
previously documented Waveshare long-message concern has not been
diagnosed or fixed by this code. No LoRaWAN certification is claimed.

The [2026-10-27 host validation record](../../tests/hardware/zero2w-lorawan-software-2026-10-27.md)
records exact dependencies and checks for this software checkpoint.
