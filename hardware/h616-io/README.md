# Zero 2W I²C, UART and PWM controls

| Menu | Command ID | When a change takes effect |
|---|---|---|
| I²C bus clocks | `I2C001` | Next Linux boot, on one physical controller |
| UART baud and framing | `UART01` | Live framing or a saved physical-port boot profile |
| Header PWM1 | `PWM001` | Saving the profile leaves the pin alone. Start or restart explicitly to drive pin 32. |

## TWI bus clocks

H616 has five main-domain controllers (TWI0…4, APB2 clock) and one standby
controller (S_TWI0, APBS2 clock). Standard-mode supports up to 100 kHz and
Fast-mode up to 400 kHz. The control register at offset 0x14 has M=0…15 and
N=0…7. In master mode SCL = Fin / [10 × (M+1) × 2ᴺ]. The manual describes a
divide-by-11 exception with M=0 and 40% duty. The Armbian mv64xxx driver
writes the M/N fields with the duty bit clear. It tries N first and chooses
the largest integer-Hz result at or below the request. The Linux default
when the controller node has no `clock-frequency` is 100 kHz.
[Allwinner H616 manual, §§9.1.1 and 9.1.3.2](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf#page=573) · [TWI_CCR, §9.1.6.6](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf#page=587) · [Linux mv64xxx driver](https://github.com/torvalds/linux/blob/v6.18/drivers/i2c/busses/i2c-mv64xxx.c)

For a 24 MHz input the model has 67 distinct in-range integer outputs,
from 1,171 to 400,000 Hz. Requests of 100 and 400 kHz are exact; 250 kHz
gives 240 kHz. The menu shows the source of the input rate. When the
controller's CCF debugfs rate is unavailable it explicitly uses the manual's
24 MHz example. A subsequent clock-tree change can change the result.

```sh
sudo armbian-config-zero2w --api module_i2c_clocks list
sudo armbian-config-zero2w --api module_i2c_clocks grid twi1
sudo armbian-config-zero2w --api module_i2c_clocks status twi1
sudo armbian-config-zero2w --api module_i2c_clocks set twi1 100000
sudo armbian-config-zero2w --api module_i2c_clocks default twi1
sudo armbian-config-zero2w --api module_i2c_clocks backups
sudo armbian-config-zero2w --api module_i2c_clocks rollback change.ID
```

All clients on a bus share SCL. The stock standby bus carries the board PMIC.
The DFR0528 uses TWI1 via i2c1-pi (physical 3 SDA/PI8 and 5 SCL/PI7).
Its MCU at address 0x10 exposes battery telemetry. DFRobot does not give a
maximum external SCL in the HAT protocol reference. Both settings were
exercised on the virtual MCU. Physical 400 kHz qualification still requires
successful telemetry and SDA/SCL timing checks with the actual HAT, pull-ups
and bus load. The clock manager changes only the controller clock property.
It preserves the battery node, pinmux, other buses and SPI settings. One
shared lock covers validation and boot configuration changes. Rollback checks
that the saved successor still matches before restoring the earlier file.
[DFRobot MCU protocol](https://wiki.dfrobot.com/dfr0528/docs/19883)

## UART

The [UART overlay and boot-profile guide](uart-boot.md) lists physical pins, persistent settings and boot rollback.

The six H616 UARTs use a nominal baud of SCLK / (16 × divisor), with a
16-bit divisor. The manual's examples use several input clocks for the high
baud rates. A request accepted by termios does not measure wire baud.
`UART01` discovers enabled DW APB UARTs by their DT node, independently of
tty numbering. The manual specifies two-wire UART0/UART5 and four-wire
UART1–UART4; RTS/CTS also requires the corresponding board pinmux. The
menu offers Linux baud constants up to 4 Mbaud, 5–8 data bits,
none/even/odd parity and 1 or 2 stop bits (1.5 for a five-bit frame).
Unrelated tty settings including flow control are preserved.
[H616 UART baud table, §9.2.3.5.2](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf#page=598)

```sh
sudo armbian-config-zero2w --api module_h616_uart list
sudo armbian-config-zero2w --api module_h616_uart set ttyS2 57600 7 even 2
sudo armbian-config-zero2w --api module_h616_uart rollback ttyS2
```

Use a tty returned by `list`. The control checks kernel consoles and open
descriptors and takes an exclusive tty before changing its settings. A UART
used by gpsd, getty or another client is left to its owner. Opening an idle
tty for status or configuration can affect modem control lines. Runtime
changes are read back; a later application can select its own settings.
An intervening framing change prevents undo. Boot console selection remains
in its separate console menu.

## PWM

The H616 PWM block has OSC24M/APB1 input clocks, a first-stage divider,
a prescaler, period and active-cycle counts and polarity control.
The supported Zero 2W header route is PWM1 on PI11, physical 32, with the
stock `pwm1-pi11` overlay. The menu uses the kernel PWM ABI. It checks the
route and the six-channel `300a000.pwm` controller before exporting PWM1.
[H616 PWM clock and waveform, §9.9](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf#page=779)

```sh
sudo armbian-config-zero2w --api module_h616_pwm set 1000 37.5 inversed
sudo armbian-config-zero2w --api module_h616_pwm start
sudo armbian-config-zero2w --api module_h616_pwm status
sudo armbian-config-zero2w --api module_h616_pwm stop
```

The saved profile accepts 1 Hz–1 MHz (the project's 1 µs–1 s period range),
0–100% active duty in steps of 0.01%, and normal (active-high) or inversed (active-low) **profile**. The stock vendor
driver forces hardware polarity to normal on enable, so the helper always
uses normal kernel polarity and computes the high interval. At 1 kHz and
37.5% active-low it requests 625,000 ns high and 375,000 ns low. This
preserves steady-state widths; it does not promise an inverted first edge,
phase alignment with another channel or a fixed idle level after release.
Kernel readback shows the requested high interval in nanoseconds.
The unit has no automatic boot activation. Saving a new waveform leaves
running output unchanged until restart. Stop releases only the channel
exported by this service. The separate PWM5 Ethernet clock is untouched.
