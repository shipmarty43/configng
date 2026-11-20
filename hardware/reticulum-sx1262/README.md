# Reticulum over the Waveshare SX1262 433 MHz HAT

**System → Hardware → SX1262 mode** (`sudo armbian-config-zero2w --cmd SXMD01`) now has **Check Reticulum hardware profile (read only)** and **SPI bus clock (Hz)**. The prepared hardware interface receives RNode normal-mode LoRa frames, reassembles them and presents them to Reticulum's standard `RNodeInterface`. Hardware transmission is disabled. The Zero 2W test installation stays in `no-radio / Off`.

## Two separate clocks

| Setting | Tested profile |
|---|---|
| Host SPI | Mode 0 (CPOL=0, CPHA=0), 8 bits, MSB first, active-low kernel CS0 on PI3. Default 2,000,000 Hz. Requests range from 3,000 Hz to the smaller of the live DT limit and 16 MHz. [H616 clock grid and examples](../sx1262-mode/spi-clock.md). |
| LoRa modem | 433,875,000 Hz, 125 kHz bandwidth, SF9, CR 4/5, explicit header, 18 preamble symbols, CRC on, standard IQ, private sync word 0x1424. Set the peer to the same PHY profile. |

The selector writes `/etc/armbian-config/sx1262-spi-hz` atomically. Updated Reticulum, Meshtastic and LoRaWAN backends read it on their next start. The kernel clock generator determines the physical SCLK rate. The LoRaWAN component must be rebuilt to use the new setting. Portduino can restore its 2 MHz idle default between transactions; the Meshtastic fixture checks the effective requested speed at each transfer.

```sh
sudo armbian-config-zero2w --api module_sx1262_mode spi
sudo armbian-config-zero2w --api module_sx1262_mode spi 500000
sudo armbian-config-zero2w --api module_sx1262_mode spi default
sudo armbian-config-zero2w --api module_sx1262_mode check-reticulum
```

## Hardware and host contract

The adapter reuses the Zero 2W [route and device binding checks](../meshtastic-sx1262/README.md). It holds the shared owner flock before opening hardware. Its spidev setup writes and reads back MODE32, bit order, word length and clock, then submits one kernel-CS transaction per command with the selected speed. GPIO uses libgpiod v2. The chip is in standby between host sessions. DIO1 indicates a received packet or error; damaged frames clear the partial datagram. The external switch is high during RX. The receive driver has an SPI opcode allowlist which excludes FIFO writes for TX, SetTx, CAD and continuous test transmissions.

On selecting the qualified hardware backend, the worker binds **127.0.0.1:7633** and signals systemd readiness. Its companion attaches only the named, normally disabled RNode entry to the existing `rnsd` and verifies it is online. Stopping detaches that interface and releases the radio lock. The board's LAN/TCP interface has an independent lifecycle.

The KISS subset implements device detection, a **1.52 host compatibility level**, fixed PHY configuration and readback, radio on/off, escaping, packet delivery, leave and flow control. The platform/MCU fields are unspecified. The interface advertises `outgoing=no` in RNS. A host DATA request to the hardware backend returns `ERROR_TXFAILED` without touching SPI. The required host field `txpower=0` is a handshake value. EEPROM programming, firmware update, display, battery/airtime telemetry and a physical TX scheduler are outside this adapter. [Official RNS interface documentation](https://reticulum.network/manual/interfaces.html)

## SX1262 diagnostics and RNode signal quality

Open **System → Hardware → SX1262 mode → Diagnostics**. **Refresh** takes another read-only snapshot. For plain text use:

```sh
sudo armbian-config-zero2w --api module_sx1262_mode diagnostics
```

The screen shows the saved mode, pending transition, observed owner and kernel flock PID, verified SPI route and CS, next-start clock and ceiling, RNode device-access policy, radio and RNS attachment service states. Failed mode changes record their action, UTC time and reason separately from the committed selection. Error history starts when this version is installed.

The adapter publishes per-process counters once per second in its private runtime directory. This uses tmpfs and contains no packet bodies or addresses. The reader checks the active unit, PID, systemd invocation ID and snapshot age. It displays unavailable measurements if the worker is stopped, its ownership is uncertain, or its heartbeat is older than eight seconds. In the no-radio profile only the explicitly labelled software-double runtime can provide a sample. The screen never requests another SPI transfer or connects to the host's data port.

| Field | Meaning |
|---|---|
| Worker SPI request / host | Clock requested by the running worker and whether its host is disconnected, connected in standby or receiving |
| Valid frames / complete packets | Non-empty LoRa frames with good IRQ status, and fully reassembled RNode datagrams |
| CRC / header errors | Separate IRQ flag counters. One IRQ can carry both flags. |
| Split counters | Abandoned partial datagrams, orphan short fragments, and presence of a pending first fragment. Timeout, replacement, error or disconnect can abandon a partial. |
| Last RSSI / SNR / age | Quality of the last frame of the last complete datagram, and seconds since its reception. CRC errors and incomplete datagrams preserve the previous sample. A new worker starts with empty signal fields. |

The RX driver reads the three-byte LoRa `GetPacketStatus` result before rearming RX. The screen retains RSSI in half dBm and signed SNR in quarter dB. Before a KISS DATA frame the adapter emits `CMD_STAT_RSSI` (whole dBm truncated toward zero, offset 157) and `CMD_STAT_SNR` (signed quarter dB). The project RNS application therefore receives −103 dBm for a screen reading of −103.5 dBm, and the same −7.25 dB SNR. [Semtech's LoRa packet-status implementation](https://github.com/Lora-net/sx126x_driver/blob/master/src/sx126x.c) · [Reference RNode KISS indications](https://github.com/markqvist/RNode_Firmware/blob/56775c51b60a6190242e324c210997dcc7637e53/Utilities.h)

**Pinned host decoder.** Stock RNS 1.6.1 reads the escaped SNR bytes for −16 and −9.25 dB as −9 and −8.75 dB. The screen uses the SX1262 values directly. The included [host patch](rns-1.6.1-signal-escape.patch) also fixes the two KISS metric commands in the project's Linux RNodeInterface. The apply script checks the installed version and exact source digest, accepts an already applied fix and supports `revert`. It only edits the private mesh venv. New Python processes load the correction; after reinstalling stock RNS 1.6.1, reapply it if needed.

### Board test without RF, 2026-11-20

On Zero 2W the ARM64 SPI/libgpiod fixture supplied packet-status bytes `cf e3 50`; the native adapter decoded −103.5 dBm / −7.25 dB before rearming. A registered RNS application received the completed payload and its corresponding RSSI/SNR. The client tests covered SNR values 0, +4.25, −7.25, −16 and −9.25 dB before and after the decoder fix. Unit tests round-trip all 256 signed SNR byte values with standard KISS escaping.

The installed 80×24 terminal displayed 9 valid frames, 6 complete packets, one CRC error, one header error, one abandoned split and one orphan. After pausing the test worker for ten seconds, Refresh showed stale telemetry and blank signal fields. Refresh showed the sample again after resuming. Switching to Off removed the test owner and its measurements. The production radio unit stayed inactive, with no bound devices.

To repeat the signal comparison with the [no-radio userspace model](tests/check_diagnostics.py), use a private loopback and device namespace. From the fork checkout on the board:

```sh
tests=$PWD/hardware/reticulum-sx1262/tests
sudo systemd-run --quiet --wait --collect --pipe -p PrivateNetwork=yes -p PrivateDevices=yes \
    -p DevicePolicy=closed -p PrivateTmp=yes -p CapabilityBoundingSet= -p ProtectSystem=strict \
    -p NoNewPrivileges=yes -p MemoryMax=160M -p TasksMax=64 -p RuntimeMaxSec=80 \
    -p RuntimeDirectory=opi-rnode-diag-acceptance -p "BindReadOnlyPaths=$tests:/run/opi-rnode-checks" \
    --setenv=PYTHONPATH=/opt/opi-mesh --setenv=PYTHONDONTWRITEBYTECODE=1 \
    /opt/opi-mesh/venv/bin/python /run/opi-rnode-checks/check_diagnostics.py --patched-host
```

Omit `--patched-host` when testing the original RNS 1.6.1 reader.

## Install in sealed mode

Use the built configurator and the existing Zero 2W mesh environment. The board used RNS 1.6.1, pyserial 3.5 and Ubuntu's `python3-libgpiod` v2 visible in the mesh venv. From the fork checkout:

```sh
sudo apt-get install --no-install-recommends python3-libgpiod
sudo install -m644 share/armbian-config/sx1262_spi.py /opt/opi-mesh/
sudo install -m644 hardware/meshtastic-sx1262/{sx1262_profile.py,zero2w-waveshare.yaml.in} /opt/opi-mesh/
sudo install -m644 hardware/reticulum-sx1262/{rnode_adapter.py,rnode_link.py,rnode_wire.py,rnode_metrics.py,sx1262_rx.py,rnode-interface.conf} /opt/opi-mesh/
sudo install -m644 hardware/reticulum-sx1262/*.service /usr/local/lib/systemd/system/
sudo bash hardware/reticulum-sx1262/apply-rns-signal-fix.sh
sudo systemctl daemon-reload
```

New installations use [the supplied Reticulum config](../mesh/reticulum.conf). For an existing installation, merge the single section from `rnode-interface.conf` under `[interfaces]` in `/etc/opi-mesh/reticulum.conf`. The shared daemon uses `/var/lib/opi-reticulum/config`; keep the section there for a live attach, or let the service copy it at its normal next start. The two entries on the tested board were installed disabled without restarting its running services.

No device bindings or boot enablement are supplied. Hardware preflight requires the hardware selector profile and a matching site-specific device drop-in. Both radio units are gated on its presence. The main service has closed device policy, private devices and local-only IP access. The read-only check works with the gates closed.

## RNode interoperability and SPI acceptance — Zero 2W, 2026-11-20

| Check | Observed result |
|---|---|
| Official peer | Compiled the original `transmit()` and `receive_callback()` paths from [RNode_Firmware revision 56775c51](https://github.com/markqvist/RNode_Firmware/tree/56775c51b60a6190242e324c210997dcc7637e53) against a memory FIFO. Used the upstream normal-mode header helpers and MTU definitions. The radio has a 255-byte frame limit, including its one-byte header. |
| Interoperability | The unmodified RNS 1.6.1 RNodeInterface detected the adapter over TCP, read back frequency/BW/SF/CR and came online. Compared exact payloads of **1, 2, 253, 254, 255, 256, 500, 507 and 508 bytes**, including KISS delimiter and escape bytes. Reference TX → adapter RX and virtual adapter TX → reference RX both passed. The 508-byte upstream TX may emit a trailing header-only frame; the receiver drops it. |
| RNS application | Used the normal shared-instance attach/detach RPC. A packet framed by the upstream code traversed the modeled FIFO, adapter and official RNodeInterface, and reached a registered RNS application callback intact. |
| Hardware path without devices | Bound ordinary files at the SPI/GPIO paths inside a private device namespace. The same ARM64 Python, Linux SPI ioctl and libgpiod paths used by the hardware worker configured mode 0, 8-bit MSB-first and the requested clock, pulsed reset, enabled DIO2, selected the RX switch, cleared a CRC error and rearmed RX. The KISS TX request was rejected. The worker signalled READY, held the test flock under its MainPID, answered a loopback detection request and released the lock on stop. |
| Clock menu | Read the actual menu, rejected 2,000,001 Hz without saving, selected 500,000 Hz and restored the DT default of 2,000,000 Hz. Checked Reticulum and the compiled LoRaWAN SPI transport at both speeds and Meshtastic transfers at 500,000 Hz. The real board bus was never opened. |

The two fragments carry only a four-bit sequence and split flag. This cannot distinguish every collision or duplicate full-sized fragment. The adapter bounds reassembly to 508 bytes, requires a full-sized first fragment, and expires stale partial data after ten seconds. The tests check replacement, orphan and corrupted fragments. Radio reception, physical SCLK/CS waveform, link reliability and exchange with an independent physical RNode remain bench tests.

### Repeat without RF

Use a checkout of the pinned upstream revision for the independent framing oracle. The builder verifies the source hashes before compiling only the framing functions. On the board:

```sh
tests=$PWD/hardware/reticulum-sx1262/tests
work=$(mktemp -d)
python3 "$tests/build_reference.py" /path/to/RNode_Firmware "$work/oracle"
sudo systemd-run --quiet --wait --collect --pipe -p PrivateNetwork=yes -p PrivateDevices=yes \
    -p DevicePolicy=closed -p PrivateTmp=yes -p ProtectSystem=strict -p CapabilityBoundingSet= \
    -p NoNewPrivileges=yes -p MemoryMax=180M -p RuntimeMaxSec=100 \
    -p "BindReadOnlyPaths=$work/oracle:/run/opi-rnode-oracle $tests/check_interop.py:/run/opi-rnode-check.py" \
    --setenv=PYTHONPATH=/opt/opi-mesh --setenv=PYTHON_CPU_COUNT=1 \
    /opt/opi-mesh/venv/bin/python /run/opi-rnode-check.py /run/opi-rnode-oracle 500000
sudo bash "$tests/run-native.sh"
python3 "$tests/test_rnode.py"
```

The native fixture needs a C compiler and libgpiod v2 headers (`GPIOD_INCLUDE` can point at an extracted header directory). It never forwards device ioctls to the kernel. The full-worker test uses only a temporary profile, binding description and owner lock inside the test namespace.
