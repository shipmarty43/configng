# Zero 2W four-channel PWM acceptance

Tested on 21 November 2026 with Armbian 26.11.0-trunk.108, ARM64 and Linux
6.18.57. The original board DTB SHA-256 was
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
All eight stock PWM overlays were extracted from the regular image file.
The [PWM guide](../../hardware/h616-io/pwm-header.md) lists header pins,
console/GNSS handling, profile paths and shared clocks.

## ARM64 PWM kernel double

The existing h616-twin QEMU harness links the real Linux PWM core and a
six-channel in-memory provider. The provider accepts only channels 1–4 and
normal kernel polarity, including the project's active-low compensation.
Two isolated 256 MiB boots applied the PI and PH stock DTBO sets to the
virtual DT. On each boot, four concurrent workers produced these sysfs
readbacks:

| Channel | PI boot | PH boot | Requested frequency and active duty | High / period, ns |
|---|---|---|---|---|
| PWM1 | PI11 | PH3 | 1 kHz, 25% high | 250,000 / 1,000,000 |
| PWM2 | PI12 | PH2 | 2 kHz, 37.5% low | 312,500 / 500,000 |
| PWM3 | PI13 | PH0 | 10 kHz, 60% high | 60,000 / 100,000 |
| PWM4 | PI14 | PH1 | 20 kHz, 50% high | 25,000 / 50,000 |

Stopping PWM2 released only channel 2. The other three enables still read 1.
The shared-clock check rejected 1 Hz on PWM2 alongside the active PWM3,
and on PWM4 with the stock PWM5 clock-consumer description. The divider
calculation agreed with the compiled divider-selection loop from the vendor
kernel driver for all one million integer-Hz profile requests. The
DFR0528 driver's simulated telemetry remained available on both boots.
Virtual sysfs readback exercises the control path; it cannot measure the
signal on a physical header.

## Board DT and UI checks

- On the stock board DT, the default UART0 rejected PWM3/PH0 and PWM4/PH1.
  The separate UART0 release required a verified non-serial Linux console.
  The release/restore transaction test substituted an idle live-owner probe.
  Separate owner tests cover a kernel console, open fd and configured gpsd.
- With UART5 on PH2/PH3 or UART4 on PI13/PI14, competing PWM selections
  were rejected. Starting with PWM selected also rejected the competing UART
  overlays. The candidate boot file remained byte-identical on errors.
- The transaction suite exercised all eight overlays, one route per channel,
  duplicate selection rejection, idempotence, removal, guarded rollback and
  retention of the UPS overlay and AC300 clock declaration.
- In a real host PTY dialog, selecting PWM4 and saving 15 kHz / 31.25%
  active-low created only the PWM4 profile. No service start was requested.

## Armbian package test

A separate 640 MiB guest installed `0.1~git1423.c9c20664` from local .debs.
Through the packaged configurator, the test saved all four waveforms, enabled
all four PI pin routes, and exercised the conflicts with UART0/4/5. After a
fresh boot on the same writable layer the persisted channel settings matched
the table above. All output services were inactive. The installed PWM001
dialog rendered. Clearing PWM2 preserved the other three profile files.
The physical SD card was outside the test environment. The follow-up package
version `0.1~git1424.419c996c` installed on another copy-on-write layer
over this disk. Dpkg completed the upgrade and audit, and the existing
waveform files matched their pre-upgrade SHA-256 hashes. After saving PWM2
again, another boot verified the final package versions and all four profile
hashes, four routes and inactive outputs. With a temporary unrecognized boot
fixup present, the installed PWM001 dialog still offered live controls and
saved waveforms. The separate terminal menu test dispatched Stop to the
selected channel in that case.

Reproduce with `tests/hardware/check-pwm-overlays.sh BOARD.dtb STOCK_OVERLAY_DIR boot.scr`
and `tests/hardware/h616-twin/run.sh GPIO_SIM_OBJECTS ARM64_PYTHON_INITRAMFS.gz NEW_DIR STOCK_OVERLAY_DIR`.
The `pwm-boot` scenario of `tests/packaging/run-armbian-vm.sh` exercises the
packaged configurator across two Linux boots. Physical PWM
frequency, duty and external wiring require bench measurements.
