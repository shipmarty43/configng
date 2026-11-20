# Linux console selection on Orange Pi Zero 2W

Open **System → Hardware → Linux console TTY** or run
`sudo armbian-config-zero2w --cmd CTTY01` on the test installation.
The menu lists local virtual terminals, UARTs with an enabled device-tree node
and bound driver, and a UART plus the local display. Status shows the active
kernel consoles, the current serial login state and the consoles selected for
the next boot. Selecting a target saves it. Reboot when ready to apply it.

```sh
sudo armbian-config-zero2w --api module_console_tty list
sudo armbian-config-zero2w --api module_console_tty set tty1
sudo armbian-config-zero2w --api module_console_tty status
sudo armbian-config-zero2w --api module_console_tty backups
sudo armbian-config-zero2w --api module_console_tty rollback change.ID
```

The set command prints the backup ID. Restore that ID in the menu or CLI to
undo the change on the next boot. Rollback checks the current console settings
and keeps independent changes such as newly enabled overlays.

## Boot behaviour on the tested image

On kernel `6.18.57-current-sunxi64`, the installed U-Boot script maps both
`console=display` and `console=both` to `ttyS0,115200` plus `tty1`. The
selector verifies the script and sets `console=custom` and explicit
`consoleargs` in `/boot/armbianEnv.txt`. A kernel command-line mask suppresses
the released UART's serial login for that boot, including an explicitly enabled
serial-getty. The feature controls Linux from kernel startup onwards. Early
U-Boot input and output use the bootloader's own settings.

## Board check, 2026-11-20

| Check | Observed result |
|---|---|
| Save, restore, save again | Restoring the first change reproduced the original environment byte for byte. Reapplying `tty1` preserved the overlay selections. |
| Reboot into `tty1` | SSH reconnected. Both `/proc/consoles` and `/sys/class/tty/console/active` showed only `tty1`. The serial getty on `ttyS0` was inactive and masked for this boot. LightDM was active. |
| Installed configurator | The interactive menu offered `tty1` through `tty6`, `ttyS0`, `ttyS0+tty1` and rollback. Opening Status displayed the active console. |
| Waveshare L76K on header pins 8/10 | At 9600 baud, 8N1, the first 16-second read received zero bytes. After the operator set GPS STANDY to OFF and pressed SET, a 30-second read received 8,870 bytes and 297 complete, checksum-valid NMEA sentences, with zero checksum failures. |
| Satellite fix | All 30 RMC sentences reported V and all 30 GGA sentences reported fix quality 0. The UART link was verified. A position fix remains to be tested. |

The NMEA check opened the UART read-only and restored the previous serial
settings after sampling. No coordinates were recorded. Waveshare documents the
standby switch, wake button and default baud rate in the [HAT hardware description](https://www.waveshare.com/sx1262-lorawan-hat.htm).
