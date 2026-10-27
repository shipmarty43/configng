# DFR0528 in the overlay manager — 2026-10-27

The existing `module_devicetree_overlays` handled stock overlays only. On Zero
2W its editor now offers stock overlays and **DFR0528 UPS**. The UPS controls
live in a separate `module_ups_dfr0528` source file. The existing assembly process
includes it in the runtime library; other boards retain the stock editor.

## User entry points

The tested build is installed on the board under `/opt/armbian-config-zero2w`,
with launcher **`sudo armbian-config-zero2w`**. The packaged `/usr/bin/armbian-config`
was not replaced. Open **System → Hardware → Device Tree Overlays → DFR0528 UPS**.
Direct commands:

```sh
sudo armbian-config-zero2w --api module_devicetree_overlays ups status
sudo armbian-config-zero2w --api module_devicetree_overlays ups enable
sudo armbian-config-zero2w --api module_devicetree_overlays ups disable
```

This controls the already-installed driver/DTBO; it is **not** an automatic
DKMS/header downloader or installer for a clean image. Use the
[driver installation instructions](../../hardware/dfrobot-ups/README.md) first.
Status distinguishes live telemetry from the next-boot selection.

Enable verifies the Zero 2W, current-kernel module, recognized boot script and
composed DT. It adds stock `i2c1-pi` and user `zero2w-dfr0528`, retaining other
entries. The composed result must contain the expected device address/compatible,
enabled I2C1 and PI7/PI8 route. Unknown boot paths, fixup parameters, duplicate
DT keys, invalid names, missing blobs and conflicting overlays are refused.

Disable removes only the UPS user overlay. It retains the shared I2C bus and
installed driver. The stock editor/API now refuses removal of `i2c1-pi` while
the UPS overlay remains enabled. Boot writes share a lock, preserve permissions,
save backups and use an atomic rename. The stock writer also now refuses failed
or unsafe backups instead of proceeding without them. No automatic reboot or
runtime unbinding is performed. The MAX17043 status limitation is unchanged.

## Validation

- Production assembly (`tools/config-assemble.sh -p`) and shell syntax checks
  passed. The existing `-t` documentation generator fails with an undefined
  `create_markdown_technical`; this unrelated generator issue was not changed.
- 18 host UPS tests passed, including actual DT compilation/composition,
  corrupt/conflicting DT, missing dependencies, unsafe paths, failed rename,
  concurrent edits, preservation of Pi writer format, TUI routing and cancellation.
- 16 UPS tests passed on AArch64; the final two Pi-format/dependency-release cases
  were run on the host. All 18 existing USB-role tests passed on host and board.
  These USB tests use fixtures; no USB role or modem was tested on real hardware.
- Through the assembled main CLI, status reported the installed driver and live
  battery; enabling an already-enabled UPS was a no-op.
- A real next-boot disable/enable cycle restored `/boot/armbianEnv.txt` byte for
  byte. Live `power_supply` stayed available. Backups remain under
  `/boot/armbianEnv.txt.ups-backups/`; no reboot was needed for this UI test.
- Opened the real dialog over SSH PTY, selected the UPS submenu and displayed
  live status (51%, 4.095 V, `Unknown`), then cancelled without changes.
- Driver autoload and battery indication after reboot were already verified in
  the [UPS report](zero2w-ups-2026-10-27.md). The UI test did not repeat that reboot
  or qualify a different kernel/image.

Logs and tested source hashes are in
[the manager evidence directory](evidence/2026-10-27-ups-manager/). Full boot
backups were retained privately outside the SD card.
