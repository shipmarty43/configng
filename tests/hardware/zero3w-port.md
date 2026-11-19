# Orange Pi Zero 3W (A733) port assessment

2026-11-19. Target: **Orange Pi Zero 3W**. Baseline: Orange Pi Zero 2W (H618).
This is a schematic, source and host-test review. No Zero 3W hardware has been qualified.

## Offline reference library

The project workspace holds the original PDFs in `reference-docs/` alongside the
repository checkouts. To verify that directory, run
`sha256sum -c ../configng/tests/hardware/soc-reference.sha256` from inside it.
The links below locate the originals for another checkout. Page numbers in this
table are PDF viewer pages.

| Local PDF | Pages | What to use it for | Source |
|---|---:|---|---|
| Allwinner_SoC_Solution_Catalog_2026-03.pdf | 59 | H618 overview on p. 36 | [Allwinner](https://www.allwinnertech.com/uploads/download_source/20260303162657a4.pdf) |
| H616_User_Manual_V1.0.pdf | 831 | Related silicon, §3.1 memory map, §7.2 TVE, §9 interfaces. The upstream Zero 2W DTS includes the H616 SoC description. Validate each block against the running DT. | [Allwinner manual on linux-sunxi](https://linux-sunxi.org/images/1/1d/H616_User_Manual_V1.0.pdf), [Linux Zero 2W DTS](https://github.com/torvalds/linux/blob/v6.18/arch/arm64/boot/dts/allwinner/sun50i-h618-orangepi-zero2w.dts) |
| OrangePi_Zero2w_H618_User-Manual_v1.1.pdf | 331 | Existing board and expansion connector | [Orange Pi manual, mirrored copy](https://www.nikom.biz/pic_info/A704017/OrangePi_Zero2w_H618_User-Manual_v1.1.pdf) |
| A733_Datasheet_V1.01.pdf | 151 | Package, electrical characteristics, GPIO alternate functions (§4.2, p. 63) | [Allwinner Tina SDK](https://gitlab.com/tina5.0_aiot/product/docs/-/blob/d0dc4d615be00b76e3a0818d0818eff8f69ffa15/A733/Hardware%E7%A1%AC%E4%BB%B6%E7%B1%BB%E6%96%87%E6%A1%A3/%E8%8A%AF%E7%89%87%E6%89%8B%E5%86%8C/A733_Datasheet_V1.01.pdf) |
| A733_User_Manual_V1.00.pdf | 1938 | §2 Arm memory map. PWM §18.7, SPI §18.8, UART §18.10, TWI §18.11, GPIO §18.14 | [Allwinner Tina SDK](https://gitlab.com/tina5.0_aiot/product/docs/-/blob/d0dc4d615be00b76e3a0818d0818eff8f69ffa15/A733/Hardware%E7%A1%AC%E4%BB%B6%E7%B1%BB%E6%96%87%E6%A1%A3/%E8%8A%AF%E7%89%87%E6%89%8B%E5%86%8C/A733_User%20Manual_V1.00.pdf) |
| OrangePi_Zero3W_V1_2_Schematic.pdf | 18 | Board power, SoC signals (sheet 9), header (sheet 18) | [Xunlong schematic V1.2](https://drive.google.com/file/d/1layhtSvMpQo-z_iMJjNfNVvhPhObpsvW/view) |
| OrangePi_Zero3W_V1_5_DSN.pdf | 18 | Second board drawing. The distributor filename says V1.5, while sheet 18 retains a V1.2 title block. Relevant header nets agree in both PDFs. | [Xunlong drawing labelled V1.5](https://drive.google.com/file/d/1LWNa-VwCVXKQ4rQheLolr_EWw8pe3zkn/view) |

## Board wiring and driver implications

Physical pin numbers below are on the 40-pin header. Zero 3W routing comes
from sheets 9 and 18 of the two Xunlong drawings. Zero 2W mapping comes from
the [existing HAT profile](zero2w-radio-ecosystem.md#standard-shield-mapping).

| Peripheral signal | Physical pins | Zero 2W | Zero 3W | What to verify |
|---|---|---|---|---|
| DFR0528 SDA / SCL | 3 / 5 | PI8 / PI7 | PB3 / PB2, TWI0 | Enable the header bus, bind the DFR0528 MCU at 0x10, compare voltage and capacity in power_supply and UPower. |
| L76K host TX / RX | 8 / 10 | PH0 / PH1 | PB9 / PB10, UART0 CPU debug, series 1 kΩ | Check bootloader output, kernel console and getty before assigning this UART to gpsd. |
| SX1262 MOSI / MISO / SCLK | 19 / 21 / 23 | PH7 / PH8 / PH6 | PE2 / PE3 / PE1, SPI3 | Compose DT against the selected image, check pinmux and real SPI exchange. |
| SX1262 CS / RESET | 40 / 12 | PI3 / PI1 | PB7 / PB5 | The shield selects on physical 40. Header SPI3 CS0/CS1 are on 24/26. Qualify software CS with SPI_NO_CS or implement a single DT GPIO CS owner. |
| SX1262 DIO1 / BUSY / TX enable | 36 / 38 / 31 | PC12 / PI4 / PI15 | PD2 / PB8 / PE13 | Check edge events, BUSY, antenna switch and conflicts with alternate functions. |
| Earlier Zero 2W PWM test output / input | 32 / 29 | PI11 / PI0 | PD1 (PWM0-1) / PE12 | Identify the correct PWM chip/channel and measure a new loopback. |

The vendor Zero 3W DTS disables SPI3 and TWI0 by default. Its root compatible
actually says `xunlong,orangepi-4-pro` and `arm,sun60iw2p1`. Check the DTB
that shipped with the selected image, its identity and header net groups before
enabling a profile. Matching every 4 Pro or every sun60iw2 board would also
select other layouts. Armbian has a board definition with a Zero 3W-specific
boot0, `sun60i-a733-orangepi-zero3w.dtb` and vendor kernel target. Its
`HAS_VIDEO_OUTPUT="no"` flag describes the build's desktop availability.
[Vendor DTS](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/arch/arm64/boot/dts/allwinner/sun60i-a733-orangepi-zero3w.dts)
· [Armbian board definition](https://github.com/armbian/build/blob/55152d1a7d4a8f28ed39124f1d8584745fa91193/config/boards/orangepizero3w.conf)

The manuals also show different register maps. GPIO / TWI0 / SPI0 bases are
0x0300B000 / 0x05002000 / 0x05010000 for H616 and
0x02000000 / 0x02510000 / 0x02540000 for A733. These explain why the H618
pinctrl identification and register assumptions do not carry over. Keep GPIO,
SPI and I²C access through the kernel interfaces.

## Portability by subsystem

| Area | Reusable part | Zero 3W work |
|---|---|---|
| WiringPi, Python, overlays | C GPIO character-device operations, SPI transfers, serial API and host tests | New board identity, GPIO chip discovery, physical map, bias/IRQ/PWM and board-specific overlays. The H618 backend filters pinctrl labels and both DT compatibles. |
| configng CPU and desktop | CPUFreq policy enumeration, module UI, display settings where the same desktop stack is present | Check governor/frequency limits per A55/A76 policy, persistent settings and rollback. Establish working KMS/desktop before display-manager and hotplug tests. |
| DFR0528 UPS | MCU driver, percentage/voltage, UPower | Port the TWI overlay and configurator guards. Assess the power path independently: DFRobot rates the output at 5 V / 2 A. Zero 3W drawing shows 5 V / 3 A on sheet 1 and 2 A input on the 5 V header on sheet 18. Qualify board plus USB hub/modem load before using battery power. Zero 2W support stays accepted. [DFRobot specifications](https://wiki.dfrobot.com/dfr0528) |
| Radio and GNSS | RadioLib LoRaWAN MAC/state, service/client protocols, ModemManager and gpsd APIs | Current HAL checks Zero 2W and its numeric GPIOs. Add a Zero 3W HAL/profile. Qualify Waveshare peer/gateway, L76K and USB SIM7600G-H separately, then the planned source selector. |
| USB | ModemManager/NetworkManager settings and Linux gadget functions | Map physical connectors, Type-C role and VBUS control. Replace Zero 2W DT guards/paths and verify role changes leave the hub and modem available. |
| Graphics, compute and video | Test workloads, reference frames, post-warmup browser metrics | A733 has PowerVR BXM-4-64 MC1. Zero 2W has Mali-G31. Qualify the matching kernel/userspace GPU stack, verify Vulkan compute output, then independent encode/decode and browser decoder selection. |
| Native composite output | PAL/NTSC capture method | The Zero 2W manual documents expansion TV-out. We found no corresponding connector/net on the Zero 3W drawings. A733 register text mentions CVBSOUT clock inputs. That alone does not establish a routed DAC. Keep native CVBS as a Zero 2W task unless a Zero 3W board route is documented. |

Chip specifications: [H618](https://www.allwinnertech.com/index.php?a=index&c=product&id=89) · [A733](https://www.allwinnertech.com/index.php?a=index&c=product&id=139).

## Project check and task order

Inspected configng ee3b89bf, WiringPi f627770 and armbian-gui caa06d8 on
2026-11-19. The fork's target-specific code is in `wiringPiH618.c`,
`hardware/lorawan/hal.hpp`, `module_usb_role.sh` and `module_ups_dfr0528.sh`.
The GUI's main.yaml and SX1262 driver still default to 868 MHz, unlike the
433 MHz shield and the configng LoRaWAN component.

Host checks: WiringPi host-test (ASan/UBSan, leak detection disabled), 65 Bats
cases covering CPU, displays, LoRaWAN and modem controls, all three LoRaWAN
CTest groups, and five firmware-reader unit tests passed. For the uninstalled
WiringPi library the host CLI test required its runtime name libwiringPi.so on
the library search path. The GUI check covered static parsing of 51 Python
files, the YAML configuration and Bash launcher syntax.

1. Baseline a dedicated Zero 3W SD with the PCB revision, image, kernel and live DT.
   Compare its actual nodes and enabled pin groups with the two schematic sheets.
2. Add a separate WiringPi board profile and fixtures, then test bus exchange,
   IRQ, PWM and the Python binding. Preserve Zero 2W regression coverage.
3. Add TWI0/SPI3/UART overlays, a single radio owner and rollback. Test DFR0528
   telemetry, followed by L76K and receive/status on the radio.
4. Validate Class A OTAA with a gateway, Meshtastic and Reticulum with peers,
   and the GNSS selector with both sources. Schedule the modem trial when wanted.
5. Verify USB roles, power under load, CPU policies, then display, GPU compute,
   media playback and encoding on the chosen image. Retain kernel/package
   versions and measurements alongside the [numbered backlog](zero2w-backlog.md).
