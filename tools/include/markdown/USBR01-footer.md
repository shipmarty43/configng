### USB host / device

Inspect kernel USB data roles, registered device controllers (UDC), and the live
USB0 Device Tree. On Orange Pi Zero 2W, save a fixed **USB0** boot role using the
image's stock `sun50i-h616-usb0-host` overlay. USB1 remains host-only.

```sh
armbian-config --api module_usb_role status
armbian-config --api module_usb_role boot host
armbian-config --api module_usb_role restore
armbian-config --api module_usb_role boot device
```

Save and restore change the **next boot**, not the running USB controllers. No
reboot is automatic. Disconnect USB0 peripherals and verify the supply/cable
arrangement before rebooting: host requires a suitable host/OTG adapter and board
power; device connects to a host with a data cable. Role selection does not manage
VBUS, negotiate Type-C power, or make two power supplies safe to connect together.
With UPS power and a modem/hub on USB1, leave USB1 cabling unchanged during testing.

Device role alone does not enumerate as a COM port, network adapter or disk.
Those require a separate gadget function; this module does not bind/unbind
existing gadgets or export storage.

The preview boot backend requires an explicit
`fdtfile=allwinner/sun50i-h618-orangepi-zero2w.dtb`,
`overlay_prefix=sun50i-h616`, the conventional Armbian `boot.scr` loading route,
and `device-tree-compiler` (`fdtget`, `fdtoverlay`). It rejects extlinux boot,
`user_overlays`, `param_*` fixups, custom overlay paths and duplicate DT keys.
It applies the proposed stock overlays offline and verifies USB0 mode, PHY,
EHCI/OHCI and unchanged USB1 controller status before writing. It does not
emulate arbitrary U-Boot scripts or qualify another board/kernel image.

One pending before/after backup is kept at
`/boot/armbianEnv.txt.usb-role-backup/`. Restore it before saving another setting.
Restore refuses to overwrite intervening manual edits. Do not run another boot
editor concurrently. Data is synced and the environment is replaced atomically;
a power failure can still require manual recovery. An incomplete backup is
retained for inspection instead of silently replacing the original settings.

If the board cannot boot after a change, mount its boot filesystem on another
computer and compare `armbianEnv.txt` with the backup's `before` and `after` files.
Restore `before` only after accounting for any later edits. Do not delete the
backup until the board boots and the saved settings are verified.
