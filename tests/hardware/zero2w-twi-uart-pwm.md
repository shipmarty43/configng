# Zero 2W TWI, UART and PWM acceptance

Tested on 21 November 2026 against Armbian 26.11.0-trunk.108, Resolute
ARM64, and Linux 6.18.57. The original board DTB had SHA-256
`4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`.
The work used regular image files and disposable overlays, with no physical
storage, network or board peripherals passed through. See the
[menu guide and manual references](../../hardware/h616-io/README.md).

| Check | Result |
|---|---|
| Clock model | Compiled the original Allwinner branch of `mv64xxx_calc_freq` and `mv64xxx_find_baud_factors` from the matching kernel with an in-memory divider structure. Compared 10,004 input/request combinations, including each divider boundary ±1 Hz, with three input clocks. The reported integer SCL, M/N fields and rejection of unreachable low requests agreed. |
| Boot integration | The original Zero 2W DTB composed with stock `i2c1-pi`, the DFR0528 DTBO and each managed TWI frequency. TWI1 retained PI7/PI8 and `ups@10`. Disabled buses, invalid requests and removing a required overlay were rejected. Concurrent SPI0 and TWI1 changes both survived; restoring TWI1 preserved SPI0. Guarded rollback restored the boot file byte for byte. |
| DFR0528 twin | Two separate 256 MiB QEMU boots, one with each generated 100/400 kHz override, used the unmodified DFR0528 overlay. A DT-enumerated virtual adapter supplied a fixed register image to the project's actual Linux battery driver. Both probes reported firmware 1.3. Linux power_supply returned 51%, 3,593,750 µV and Unknown charging status. The adapter reads the DT clock; it does not emulate wire timing or the HAT's analogue circuit. |
| PWM | Used the Linux PWM class and sysfs with a six-channel in-memory provider and simulated PI11 route. At 1 kHz: 25% active-high gave 250,000 ns high; 37.5% active-low gave 625,000 ns high. At 20 kHz, 37.5% active-low gave 31,250 ns high. A competing export was refused. TERM released the channel, and the service's cleanup path released its saved lease after SIGKILL. |
| UART PTY | ARM64 termios readback and exact restoration passed at 9,600, 115,200 and 921,600 baud, 8N1. Host tests also covered nested serial-base discovery, disabled DT ports, stop-bit combinations and invalid framing. |
| Stock Armbian / packaged CLI | APT installed the packages offline on a fresh qcow2 layer. The public TWI command saved 400 kHz, the composed DT retained DFR0528, and rollback restored the pre-change file. The real I2C001 and PWM001 dialogs rendered. The saved 20 kHz active-low PWM profile did not start the service. |
| Disconnected QEMU 16550A | Used the installed UART implementation against the second, non-console PCI serial port. Only DT discovery was substituted for the PCI route. Setting 57,600 baud, seven data bits, even parity and two stop bits was accepted and read back. A competing open descriptor blocked changes. Undo restored the previous 9600 8N1 tuple. |

The package guest used 640 MiB and a 168 MiB writable image layer. Each hardware twin boot used 256 MiB. The final sequential run recorded 744.8 MiB peak host cgroup memory and zero OOM kills.

## Repeat offline

Run from the configurator repository root with the project kernel object tree,
static BusyBox/Python ARM64 test initramfs, QEMU, dtc and the AArch64 cross
compiler available. The twin links two test-only drivers and the original
DFR0528 driver into a separate image.

```sh
python3 tests/hardware/test_h616_io.py
tests/hardware/check-i2c-clocks.sh /path/to/zero2w.dtb /path/to/i2c1-pi.dtbo
tests/hardware/h616-twin/run.sh /path/to/gpio-sim/obj /path/to/arm64-python-initramfs.gz /path/to/new-twin-dir
```

The outstanding board checks are SCL frequency and rise time under the
actual TWI1 load, repeated UPS telemetry at 400 kHz, UART pin-level baud and
framing, and PWM active/inactive widths on physical pin 32.
