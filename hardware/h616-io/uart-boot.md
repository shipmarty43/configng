# Zero 2W header UARTs at boot

Open `sudo armbian-config-zero2w --cmd UART01` and choose **Header overlays
and saved boot settings**. Select a physical controller, enable its TX/RX
route, and save baud, data bits, parity and stop bits. A disabled port can be
configured before its first boot. Reboot when ready to activate the overlay.

| Controller | Physical TX | Physical RX | SoC signals |
|---|---:|---:|---|
| UART0 | 8 | 10 | PH0 / PH1, stock console or Waveshare GNSS |
| UART2 | 15 | 22 | PI5 / PI6 |
| UART3 | 28 | 27 | PI9 / PI10 |
| UART4 | 7 | 16 | PI13 / PI14 |
| UART5 | 11 | 13 | PH2 / PH3 |

The overlay controls manage the four optional TX/RX pairs. UART0 is enabled
by the board DT; its console assignment stays in CTTY01. UART1 is outside
the documented 40-pin UART choices. The two-wire profiles preserve existing flow-control flags. UART2, UART3 and UART4 also offer four-wire boot routes with native RTS/CTS. [Orange Pi Zero 2W user manual v1.1, printed pp. 169–170 (mirror)](https://www.nikom.biz/pic_info/A704017/OrangePi_Zero2w_H618_User-Manual_v1.1.pdf)

```sh
sudo armbian-config-zero2w --api module_h616_uart routes
sudo armbian-config-zero2w --api module_h616_uart enable uart3
sudo armbian-config-zero2w --api module_h616_uart save uart3 57600 7 even 2
sudo armbian-config-zero2w --api module_h616_uart saved uart3
```

On Armbian 26.11.0-trunk.108 (6.18.57), the stock UART3/4 PI pin groups
contain `function = "uart2"`; the `uart4-pi` overlay also targets UART3.
The menu creates a private pin group and targets the controller's SoC
address. Selecting the matching canonical stock TX/RX overlay migrates
that token without editing the vendor files. The composed DT is checked for
pinmux and GPIO claims. For example UART3 shares pins with I²C2-PI, UART4
with PWM3/4-PI and UART5 with PWM on PH2/3. Claims outside DT, including
external wiring and userspace GPIO requests, require a board check.

Profiles are stored by physical UART in `/etc/armbian-config/uart/`.
A tty add event asks systemd to run `opi-zero2w-uart@ttySx.service`. The
worker resolves the live DT route and restores the setting on the matching
idle port, including termios readback. The kernel console, open ports, a
configured serial getty and the configured gpsd/GNSS receiver are checked
before applying a boot profile. Skipped owners and the applied tty appear
in the service journal. An application may subsequently configure its own
tty. Neither overlay selection nor saving a profile restarts a service or
reboots the board.

```sh
sudo armbian-config-zero2w --api module_h616_uart list
sudo armbian-config-zero2w --api module_h616_uart forget uart3
sudo armbian-config-zero2w --api module_h616_uart disable uart3
sudo armbian-config-zero2w --api module_h616_uart backups
sudo armbian-config-zero2w --api module_h616_uart boot-rollback change.ID
```

Disabling a route retains its saved framing. Forgetting a profile leaves
the running line settings alone. Boot rollback restores the matching boot
environment, including any migrated stock overlay selection. It tolerates
reordering of otherwise identical unique assignments (Armbian moves
`usbstoragequirks` at boot), and refuses changed values or added entries. The separate
runtime `rollback ttySx` undoes the last applied framing if the tty still
matches its saved state.

## Hardware flow control

In UART01 choose the port under **Header overlays and saved boot settings** and select its four-wire route. The numbers are physical 40-pin header positions in TX/RX/RTS/CTS order.

| UART | SoC pads | Header |
|---|---|---|
| UART2 PI | PI5/PI6/PI7/PI8 | 15/22/5/3 |
| UART2 PH | PH5/PH6/PH7/PH8 | 24/23/19/21 |
| UART3 PI | PI9/PI10/PI11/PI12 | 28/27/32/33 |
| UART4 PI | PI13/PI14/PI15/PI16 | 7/16/31/37 |

Use `module_h616_uart enable-rtscts uart2` for PI and `enable-rtscts-ph uart2` for PH. Use `enable-rtscts uart3` or `enable-rtscts uart4` for the other pairs. Use the existing `enable uartN` to return to two wires, or `boot-rollback change.ID` for the previous selection. DFR0528's I²C bus shares the PI UART2 handshake pins. The PH option shares SPI1's pins. UART3's handshake uses PWM1/PWM2 pins; UART4 TX/RX uses PWM3/PWM4 pins.

On tty discovery the worker checks the live four-pad mux and the tty owner before enabling and reading back `CRTSCTS`. With no saved baud/format it retains the tty's settings. Applications may subsequently set their own termios. [Validation details](../../tests/hardware/header-cs-rtscts.md)
