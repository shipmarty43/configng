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

## gpsd and opi-gnss on the board

On 2026-11-20, gpsd `3.27.5-0.1` opened `/dev/ttyS0`. It identified the
stream as NMEA0183 at 9600 baud. The device list contained that UART alone.
TCP port 2947 listened on IPv4 and IPv6 loopback. USB hotplug was disabled.
The installed `opi-gnss` service used Waveshare-only mode.

| Observation during the same 30-second interval | Result |
|---|---|
| Independent gpsd WATCH client, filtered to `/dev/ttyS0` | 91 TPV reports, all mode 1 (no fix), and 30 SKY reports. No ERROR replies. |
| Established gpsd connection owned by the running `opi-gnss` process | Its TCP receive counter advanced from 9,008 to 15,084 bytes on the same socket. A queue sample showed zero unread bytes. |
| Application status | The status snapshot advanced, Waveshare reported `acquiring`, and `source` and `fix` were null. The modem source remained disabled. |
| Persistence | `gpsd.socket`, `gpsd.service` and `opi-gnss.service` were enabled. This test ran within one boot. |

This verifies that the service receives the real UART stream via gpsd. An
outdoor satellite fix and its publication through `opi-gnss` remain open.
No coordinates were retained. [Tested configuration](../../hardware/gnss/README.md#l76k-as-the-only-receiver-on-zero-2w)
