# Zero 2W and Zero 3W GPIO electrical defaults

Open **System → Hardware → GPIO header** (`GPIO01`). All numbers refer to physical contacts on the 40-pin header. The menu shows the next-boot pad settings, shared bank filter and DT owners. **Live gpiochip consumers** reads line information without taking a line. On Zero 3W, CPU PIO and standby R_PIO are identified by their device-tree nodes. A Linux `gpiochipN` number can change at boot.

| Setting | Choices and scope |
|---|---|
| Internal bias | Up, down, off or board default for one pad. |
| Drive strength | 10, 20, 30 or 40 mA nominal pinconf drive for one pad. The drive setting takes effect when a consumer drives the pin. It does not select an output level or bank voltage. |
| Interrupt debounce | Request 1–3906 µs for the shared IRQ bank, or return to its board default. The drivers choose a clock and a power-of-two divider. The menu range covers microsecond requests through the nominal 32,768 Hz / 128 sample interval. The exact sampling period depends on the kernel clock rates. |

`default` leaves that field to the original DT/firmware, including a nonzero existing bank filter. The two kernels skip zero cells in `input-debounce`. GPIO01 uses µs throughout: H618 uses µs in DT, and A733 BSP uses **ns**. Two pins in the same bank can request the same period. Different periods are rejected, and removing one pin keeps the filter if another still requests it. The planner preserves the original cells in other banks. Existing DT IRQ consumers, including consumers outside the header, are checked before changing their bank. Examples on the tested release are PC9 (PMIC) on Zero 2W and PB6 (vendor pin test) and PL9 (Type-C) on Zero 3W.

For bias and drive, `apply.sh current` in the GPIO offline kit installs the optional driver matching the **running** kernel when that build is included. Setting a bank debounce alone works without the module. For a separate manual installation, from the extracted `release` directory:

```sh
sudo dpkg -i "./drivers/opi-header-gpio-modules-$(uname -r)_1.0-1_arm64.deb"
```

For another compatible build, install DKMS and matching kernel headers and select **Electrical preset driver** in GPIO01. The configurator package provides `/usr/src/opi-header-gpio-1.0`. An unpackaged checkout can install the Makefile, dkms.conf and opi_header_gpio.c there. The driver requests the named descriptor exclusively with `GPIOD_ASIS`, calls the gpiochip pinconf methods and releases the descriptor. A busy line or a rejected setting fails the probe. The two pinconf operations are separate kernel calls. An error on the second leaves the node unbound and the first operation may already have reached the pad. The kernel log records the failed setting. A bound preset in the live view means the boot probe succeeded. Subsequent consumers can change the settings. GPIO v2 flags report the current line request. The userspace ABI does not expose a pad-strength measurement. The bank debounce setting is processed directly by the existing pinctrl driver at boot and needs no helper module.

Examples on a free pin (29 on Zero 2W, 37 on Zero 3W):

```sh
armbian-config-zero2w --api module_header_gpio list
armbian-config-zero2w --api module_header_gpio info 29
armbian-config-zero2w --api module_header_gpio get 29
armbian-config-zero2w --api module_header_gpio set 29 up 20 244
armbian-config-zero2w --api module_header_gpio set 29 default default 244
armbian-config-zero2w --api module_header_gpio default 29
armbian-config-zero2w --api module_header_gpio backups
armbian-config-zero2w --api module_header_gpio rollback change.ID
```

The boot transaction uses the shared overlay lock and verifies the full resulting DT before committing armbianEnv.txt. Applying defaults or rolling back takes effect on the next boot. Live checks before commit inspect userspace line ownership and edge flags. A DT-declared conflict must be resolved through its owning interface. The kernel rechecks exclusive ownership when applying a pad preset. Independently running applications may request new lines later.

## Kernel behavior and offline tests

H618 6.18.57 takes the controller array in IRQ bank order A/C/D/E/F/G/H/I. Its GPIO v2 consumer interface may use the Linux software debouncer when the driver's per-line configuration is unsupported and an IRQ is available. The A733 6.6.98 vendor DT has banks B–K on PIO and L/M on R_PIO. The vendor driver derives the debounce frequency from nanoseconds; the GPIO v2 UAPI supplies microseconds. GPIO01 uses the verified boot array and accounts for the shared bank instead of issuing a per-line debounce write on this BSP. [Mainline sunxi pinctrl](https://github.com/torvalds/linux/blob/v6.18/drivers/pinctrl/sunxi/pinctrl-sunxi.c) · [Vendor pinctrl](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/pinctrl/pinctrl-sunxi.c) · [A733 main IRQ map](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/pinctrl/pinctrl-sun60iw2.c) · [A733 standby IRQ map](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/pinctrl/pinctrl-sun60iw2-r.c)

```sh
bash tests/hardware/check-header-gpio.sh "$H618_ALLWINNER_DIR" "$A733_ALLWINNER_DIR"
python3 -B tests/hardware/test_header_gpio.py
bash tests/hardware/gpio-preset/run.sh "$H618_PREPARED_HEADERS" "$ARM64_IMAGE" "$STATIC_ARM64_BUSYBOX"
```

The DT checks use the complete Armbian Zero 2W 6.18.57 and Zero 3W 6.6.98 DTBs and temporary boot media. The QEMU guest has one Cortex-A53 CPU, 256 MiB RAM, no network and an in-memory gpiochip. Electrical pull, output drive and IRQ pulse filtering on real silicon still require measurement.
