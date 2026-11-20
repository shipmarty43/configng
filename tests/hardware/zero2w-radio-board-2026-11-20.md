# Waveshare SX1262 shield on Zero 2W — first board run

Orange Pi Zero 2W, H618, Armbian kernel `6.18.57-current-sunxi64`,
Python 3.14.4. The user reported the Waveshare shield, DFR0528,
CC1101 and nRF24 attached. No live modem operations in this run.

| Check | Board observation |
|---|---|
| Boot environment before adding the HAT | Stock overlays `pwm1-pi11 i2c1-pi`, user overlay `zero2w-dfr0528`. The LoRaWAN, Meshtastic and Reticulum radio services were absent. |
| Board DTB | SHA-256 `4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758`. The new overlay passed enable/disable on a scratch copy of the actual boot environment. |
| Applied overlay | Installed `opi-zero2w-sx1262.dtbo`, enabled it with the fork's overlay module and confirmed a new boot ID after reboot. The module saved the old environment and reported the expected live endpoint after reboot. |
| SPI route | `/dev/spidev1.0`, controller `5011000.spi`, pinmux PH6/PH7/PH8, physical 40 (PI3) owned by the kernel as `spi1 CS0`. Python route discovery passed without opening SPI. |
| Other devices after reboot | DFR0528 reported 66% and 3.895 V. The PWM controller remained present at `/sys/class/pwm/pwmchip0`. No PWM output measurement. |
| Software ownership | On-board Python driver imports succeeded with staged ARM64 dependencies. Python and the C++ test helper excluded each other using the production lock. Python reacquired it after SIGKILL of the C++ holder. |
| GNSS UART | Live UART0 mux PH0/PH1 (physical 8/10). Linux console `ttyS0,115200` and active `serial-getty@ttyS0` currently own it. No NMEA capture or GNSS fix in this run. |

## Standby probe gate

The former software configured both extra radios as SPI1.1. The old image
routed hardware CS1 to PH9 (physical 26), and the nRF24 software configured
CE as physical 18. Those observations establish the previous software map.
The individual wires and the external driver of pin 18 still need identifying.

Before issuing GetStatus, the probe requested input lines with weak pull-ups
on 24 and 26 and a weak pull-down on 18, and sampled BUSY on 38. The guard
aborted before it opened spidev. An independent 250-sample input-only capture
over about 0.8 seconds showed:

| Physical pin | LOW samples | HIGH samples |
|---|---:|---:|
| 18 (candidate nRF24 CE) | 113 | 137 |
| 24 (legacy CS0) | 0 | 250 |
| 26 (legacy CS1) | 0 | 250 |
| 38 (SX1262 BUSY) | 250 | 0 |

No SPI frame, RESET pulse or radio transmission was requested. The endpoint
confirms Linux binding. The next chip-level test is a standby status read with
the other radios physically isolated or with their wiring and idle state
established. Release the header UART from console ownership before the GNSS test.
