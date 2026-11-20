# SPI0 and SPI1 device clocks on Orange Pi Zero 2W

Open **System → Hardware → SPI device clocks** (`SPI001`). Select the physical
controller and the chip select (CS). The status view shows the device-tree
path, compatible string, board default, live DT property, next-boot setting
and estimated SCLK. The grid and manual input use integer Hz. The controller
grid is also available on an empty bus. Bus identifiers follow the H618
controller addresses, independent of Linux spidev enumeration.

| Controller | Stock Zero 2W / Armbian 6.18.57 | Effect of a setting |
|---|---|---|
| SPI0, `/soc/spi@5010000` | `flash@0`, JEDEC SPI NOR, CS0, 40 MHz DT maximum | Changes the clock property seen by the Linux flash driver after boot. The operation writes boot configuration files. Flash contents and U-Boot's own SPI timing are outside its scope. |
| SPI1, `/soc/spi@5011000` | Disabled in the stock DTB | Header overlays supply the enabled devices. Each CS has its own setting. |
| SPI1 CS0 with the Waveshare SX1262 HAT | The HAT owns the chip select | Opens the existing SX1262 next-start settings, including the old 2 MHz and new 16 MHz DT ceilings. |

Minimum request is 3 kHz. The endpoint ceiling comes from the board DTB
composed with its selected device overlays **before** the clock overrides.
Consequently a downclock can later be raised again up to that ceiling. The
100 MHz controller limit and limits of recognized peripherals also apply.
For a generic spidev node, Linux cannot identify the part wired to the
header. Use the peripheral's SPI rating. The legacy example assigning
CC1101 and nRF24 to the same bus and CS describes a wiring conflict;
distinct physical devices require distinct chip selects.

```sh
sudo armbian-config-zero2w --cmd SPI001
sudo armbian-config-zero2w --api module_spi_clocks list spi1
sudo armbian-config-zero2w --api module_spi_clocks grid spi0
sudo armbian-config-zero2w --api module_spi_clocks grid spi1 1
sudo armbian-config-zero2w --api module_spi_clocks status spi0 0
sudo armbian-config-zero2w --api module_spi_clocks set spi0 0 18000000
sudo armbian-config-zero2w --api module_spi_clocks default spi0 0
sudo armbian-config-zero2w --api module_spi_clocks backups
sudo armbian-config-zero2w --api module_spi_clocks rollback change.ID
```

A change adds an immutable, per-device DTBO to `/boot/overlay-user`. The
overlay edits only the device's `spi-max-frequency` and the matching
`armbian,spi-clock-request-hz` marker for participating spidev clients.
The shared overlay manager composes and checks the complete candidate DT
before atomically replacing `armbianEnv.txt`. A saved backup retains the
previous configuration. Replacing a frequency preserves unrelated overlay
order. Reset removes the reference and restores the underlying DT property.
Old DTBOs remain available for rollback. `default-all` removes the managed
clock selections, including stale selections after manual boot edits.
A conflicting CS, a removed provider, or an edited backup successor prevents
an unsafe commit. Changes take effect on the next Linux boot.

A spidev program may set an explicit per-transfer speed. The updated
armbian-gui clients read the live properties on opening their device. With
no marker they retain their original request, clipped to any lower DT limit.
With a marker they use the selected rate up to their transport limit:

| Client | Default | Maximum client request |
|---|---:|---:|
| CC1101 | 5 MHz | 6.5 MHz for continuous SPI bursts. [TI CC1101, SPI timing table](https://www.ti.com/lit/ds/symlink/cc1101.pdf) |
| nRF24L01+ | 8 MHz | 8 MHz project profile. The datasheet's timing limits depend on output loading. [Nordic nRF24L01+ specification](https://devzone.nordicsemi.com/cfs-file/__key/communityserver-discussions-components-files/4/nRF24L01P_5F00_PS_5F00_v1.0.pdf) |
| PN532, SPI interface | 1 MHz | 5 MHz. [NXP PN532/C1 datasheet](https://www.nxp.com/docs/en/nxp/data-sheets/PN532_C1.pdf) |

Use the [divider and clock model](spi-clock.md) for the relation between
a requested speed and the physical SCLK. A DT property or spidev speed
readback is a software setting. Measuring header SCLK requires hardware.
