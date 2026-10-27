# Zero 2W USB host/device control

Checkpoint: 2026-10-27. The board was powered off when this feature was added.
**No USB role change, installation, reboot or USB enumeration was performed on
hardware.** The owner plans UPS power; USB1 has a modem and USB hub. USB0 cabling
and the UPS supply arrangement need verification before a hardware trial.

## Implementation

The separate `module_usb_role` module appears under System → Hardware →
USB host / device. It offers read-only status, next-boot host/device selection,
and restoration of the saved boot environment. The API and supported boot
layout are documented in [the menu help](../../tools/include/markdown/USBR01-footer.md).

Zero 2W USB0 is a fixed peripheral in upstream Linux DT. The CC wiring does not
implement an automatic role switch. Host mode requires a DT change enabling
USB0 EHCI/OHCI as well as setting its role. This implementation adds/removes the
image's existing `usb0-host` overlay, preserving unrelated overlay names. The
resulting tree must have the requested USB0 role and unchanged USB1 controller
status. There is no live role-switch fallback or Android sysfs/MMIO access.

Device/client role is **not a gadget function**: ACM serial, ECM/NCM networking,
and mass storage remain separate work. There is no automatic login, network
address assignment, raw-disk sharing or modification of existing gadgets.

## Local validation

59 Bats tests passed, including 18 new USB cases. USB fixtures use real `dtc`,
`fdtoverlay` and `fdtget` to build/merge isolated trees. They exercise:

- Read-only status and the distinction between live DT, UDC and boot settings.
- Host/device selection, preservation of unrelated settings and permissions.
- Exact restore, no-op, lock contention and one pending backup.
- Missing/invalid DT, conflicting USB0 settings and changed USB1 controller status.
- Unsupported boards, boot routes, fixups, user overlays and unsafe names.
- Symlinks, preparation/rename failure, external edits and cancelled dialogs.

[Local test log](evidence/2026-10-27/usb-role/local-tests.log). These are software
and DT-composition tests, not electrical or USB protocol measurements. CI runs
the same suite without GPIO/USB hardware or privileged test commands.

## Hardware acceptance still required

1. Inspect power/VBUS topology and USB0 cable. Read current DT, UDC, kernel config,
   boot script and overlays on the running image; check that this limited backend
   accepts them. Keep a copy of the boot environment off the SD card.
2. Keep the modem/hub on USB1; capture its topology and connectivity before changes.
3. Save USB0 host for next boot, reboot with suitable power/adapter, and enumerate
   a known USB device on USB0. Verify USB1 modem/hub still work.
4. Restore, reboot, and read back USB0 peripheral plus registered UDC. Test an
   explicitly configured gadget function using a data cable to a second host.
5. Exercise both directions, cold boot, exact rollback and power interruption
   recovery. Record USB1 continuity and errors; do not infer success solely from
   `dr_mode`, a loaded overlay, or an empty `usb_role` directory.

Sources:

- [Linux v6.18 Zero 2W DTS](https://github.com/torvalds/linux/blob/v6.18/arch/arm64/boot/dts/allwinner/sun50i-h618-orangepi-zero2w.dts)
- [Linux USB role ABI](https://github.com/torvalds/linux/blob/v6.18/Documentation/ABI/testing/sysfs-class-usb_role)
- [Linux gadget configfs documentation](https://docs.kernel.org/usb/gadget_configfs.html)
