# PWM002 on Orange Pi Zero 2W and Zero 3W

Open **Hardware → PWM and cooling**, or run `armbian-config-zero2w --cmd PWM002` with the offline configurator. Saved settings apply at the next boot. **Test a booted profile** performs one capture, one counted burst or a timed pair test. **Remove a saved profile** releases its boot route. **Undo a boot change** restores the previous selection and any custom fan levels.

| Board and kernel | Operation | Header routes and limits |
|---|---|---|
| Zero 2W, H618, Armbian 6.18.57 | Complementary PWM2+3 | Select both routes first in PWM001. PWM2 uses pin 33 or 11. PWM3 uses pin 7 or 8. Existing UART and console ownership applies. PWM5 supplies the Ethernet clock. |
| Zero 2W | Capture, finite burst, onboard thermal fan | The image's PWM provider lacks a capture callback and a pulse-count interface. Its DTB has no onboard PWM fan. |
| Zero 3W, A733, vendor 6.6.98 | Complementary PWM0 pairs | 0/1 on pins 7/32, 2/3 on 36/33 and 8/9 on 35/40. The stock PB6 IRQ claim blocks 8/9 until its owner releases it. |
| Zero 3W | Input capture | PWM0 channels 0, 1, 2, 3, 4, 8 and 9 use physical pins 7, 32, 36, 33, 37, 35 and 40. Standby PWM2 uses pin 28 and selector 22. The effective DT must leave the pad available. |
| Zero 3W | Finite burst | One channel emits 1–65,536 periods. The test reserves its clock peer. PWM0-4 stays unavailable for bursts while the stock fan owns PWM0-5. |
| Zero 3W | Thermal fan curve | Stock PWM0-5 uses PD5, a 25,000 ns period and levels `0 50 102 170 255`. Both CPU clusters reference this fan at 55 °C with 2 °C hysteresis. Edit all five duty levels with endpoints 0 and 255. Linux selects the cooling state. **Read live fan duty** shows the running curve, requested drive and RPM when hwmon supplies a tachometer reading. |

## Kernel support

The fan curve uses the stock `pwm-fan` driver. A stock kernel can prepare PWM profiles. Live signal tests check the parameters actually parsed by the running driver and require the corresponding patch.

* On Zero 2W the stock pair stop looks up a different DT property from the one used on start and can return with both outputs enabled. The patch closes both gates in one write, clears dead time and establishes complementary levels before opening the gates. [H618 pair patch](../../hardware/h616-io/patches/pwm-pair-stop.patch)
* On Zero 3W the stock group sequence initializes other channels' counters, including the fan's. The patch uses the individual PCR count field with the encoding `N - 1`. Completion reads the self-clearing START bit. Capture releases the selected input's IRQ, clock gate and regulator reference on completion, interruption and timeout. [A733 patch](../../hardware/a733-io/patches/pwm-capture-burst.patch) · [Pinned vendor PWM source](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/bsp/drivers/pwm/pwm-sunxi.c) · [Linux capture sysfs interface in the vendor kernel](https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/drivers/pwm/sysfs.c)

Apply the board-specific patch from the kernel source root with `git apply --check PATH_TO_PATCH` and `git apply PATH_TO_PATCH` before building the Armbian kernel package. The offline configurator installs the sources under `/opt/armbian-config-zero2w/share/armbian-config/pwm/`. The standard package uses `/usr/share/armbian-config/pwm/`. The A733 vendor kernel builds `CONFIG_AW_PWM=y`. Changing its driver requires booting the rebuilt kernel.

For pair and burst tests the period range is 1,000–2,730,666 ns on the undivided 24 MHz path. Both active and inactive intervals must exceed the quantized dead time. The accepted dead-time range is 42–10,666 ns. A setting of 500 ns gives 12 ticks. The pair test uses a userspace duration and a final disable. Killing the process with SIGKILL can leave a pair running. Bursts stop on the hardware counter.

Capture reports period and high time in nanoseconds, frequency and duty. At an undivided 24 MHz the 16-bit counter wraps in about 2.73 ms. The driver rejects windows long enough for wrap, including a slow wakeup. A retry on a steady input can give a valid sample. The sysfs timeout is one second.

## Offline acceptance, 28 November 2026

The distribution DTB SHA-256 values were `4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758` (Zero 2W) and `1eb1160f92dd1d566af920002583c67fbbb6eb35d190a62fb8f0bc1236bb74e1` (Zero 3W). The unmodified PWM source hashes were `d6ac9c8b5385556efa46cf2e6124f82c73cbc63ab5ecc0504d208e83713b386a` and `f3d7b4813d8256223c0c1c71c61e931d88bf5f39ab40236a08f16ddb4940650e`, respectively. Both patched translation units were cross-compiled for ARM64 against the distribution headers.

From the repository root, with dtc, fdtoverlay, libfdt, Python and a host C compiler installed, run

```sh
tests/hardware/check-pwm-modes.sh "$H618_ALLWINNER_DTB_DIR" "$A733_ALLWINNER_DTB_DIR"
python3 tests/hardware/pwm-modes/check-driver.py "$H618_KERNEL/drivers/pwm" "$A733_KERNEL/bsp/drivers/pwm"
python3 -m unittest discover -s tests/hardware -p 'test_pwm*.py'
```

The register double executes functions from the patched drivers. It verifies opposite polarities, 12 dead ticks, both enables cleared on stop, preservation of channel 5, a 100 µs capture with 25 µs high time, IRQ and timeout cleanup, rejection of wrap and counts of 1, 2, 17 and 65,536. The DT tests enter the fan menu, save and cancel changes, compose fan and burst profiles together, reject pin and clock conflicts, and roll back both boards. The sysfs double checks ownership, driver capabilities, ignored DT settings, abort paths and fan hwmon identity. The configurator was also assembled into a scratch Debian package and extracted. Its command catalogue resolved PWM002 to the menu and both packaged kernel patches matched the sources byte for byte.

On hardware, measure both edges of the pair including its first and last period. Count a short and a maximum-length burst with a logic analyser. Feed a known rectangular waveform to the capture pin. For the fan, verify spin-up at the lowest nonzero drive, temperature-driven state changes and return to the stock curve after rollback. Physical RPM, acoustic behaviour and electrical timing remain unmeasured.
