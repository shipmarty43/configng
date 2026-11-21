# Zero 2W UART overlay and profile acceptance

Tested 21 November 2026 using the original Zero 2W Armbian 26.11.0-trunk.108
DTB, Linux 6.18.57 and the DTBO files extracted read-only from the regular
image. The board DTB SHA-256 is
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
The [UART menu and CLI guide](../../hardware/h616-io/uart-boot.md) has the
pin table and rollback commands.

| Check | Observation |
|---|---|
| Four header routes | UART2, UART3, UART4 and UART5 were enabled together with the shipped i2c1-pi and pwm1-pi11 overlays and the DFR0528 DTBO. Each serial controller referenced its own TX/RX group with the correct pinctrl function. UART0 and the UPS node were retained. A second composition with the Waveshare SX1262 HAT also retained its SPI1 endpoint along with all four UARTs. |
| Vendor overlay correction | The original uart4-pi DTBO references uart3; both UART3/4 PI groups in the base tree name the uart2 function. Migrating the stock UART4 token enabled only UART4, left UART3 disabled and selected PI13/PI14 with the uart4 function. |
| Conflicts and rollback | I²C0/2, PWM3-PI13, PWM2-PH2, an explicit GPIO consumer and an alternative UART2 route were exercised. The manager rejected conflicting changes without replacing the boot file. An idempotent enable left it byte-identical; an intervening manual edit blocked rollback. Armbian moved its existing usbstoragequirks entry on the next boot. The UART rollback accepts an equivalent set of unique assignments while rejecting changed values, duplicate keys, or edited comments. |
| Saved profiles | Host tests verified replacing a profile, invalid framing, changed tty numbering, the live pinmux guard, busy ports, getty, console, gpsd and GNSS reservations, and forgetting a profile. A real dialog in a PTY stored UART3 115200 8N1 to a disposable profile directory. |
| Packaged cold boot | A clean Armbian ARM64 guest installed version `0.1~git1421.2fe98dfc` from local packages. Its public CLI enabled UART3, composed the DT from the guest boot files and saved 57600 7E2. On a second boot of the same qcow2 disk, the shipped udev add rule triggered the shipped systemd template without a manual start. The service logged `Restored uart3 on ttyS1`. A separate process opened the disconnected emulated 16550A and independently read back 57600 baud, 7 data bits, even parity and 2 stop bits. Forget removed the persistent profile, guarded rollback restored the original boot environment byte for byte after the restart, and the packaged UART01 dialog rendered. |

The package fixture maps the applied board DT and physical UART3 path onto
the virtual PCI ttyS1 in a unit-private sysfs view. Device enumeration by
udev, systemd activation, the persisted profile, device file, busy checks,
exclusive access and termios are real. Both boots used one vCPU, 640 MiB
guest RAM and no external network or physical-device passthrough. The host cgroup peaked at 744.2 MiB, with zero OOM kills. The writable layer occupied 170 MiB.

Reproduce the board checks with
`tests/hardware/check-uart-overlays.sh /path/to/board.dtb /path/to/stock/overlay`
and the two-boot package check with the `uart-boot` scenario of
`tests/packaging/run-armbian-vm.sh`. Boot configuration in these runs is
inside disposable files. Wiring continuity and signalling at the header
remain physical bench checks.
