# DFRobot DFR0528 battery integration

Experimental, read-only Linux `power_supply` driver for the **DFR0528 MCU**.
This is not a direct MAX17043 driver: the HAT presents a different register map
at I²C address `0x10`. No charger, cutoff, reset or address registers are written.
The driver is kept separate from the configurator shell modules so it can later
be packaged or proposed to the kernel independently.

## Hardware and supported data

On Orange Pi Zero 2W the standard 40-pin connection uses physical **3 (PI8,
SDA)** and **5 (PI7, SCL)**, controller `i2c@5002400`. Enable the stock
`i2c1-pi` overlay. Adapter numbers are dynamic: do not assume Raspberry Pi bus 1.
The custom overlay below targets the controller by DT symbol, not bus number.

The [manufacturer protocol](https://wiki.dfrobot.com/dfr0528/docs/19883)
defines product ID `0xdf`, firmware revisions 1.0–1.3, voltage in 1.25 mV units,
and SOC in 1/256 percent units. The driver exports voltage in microvolts and
integer percentage (fraction discarded, clamped to 100). Invalid or missing
telemetry invalidates the sample instead of keeping stale battery readings.
The high byte is rechecked to reject pairs crossing a register rollover.

**MAX17043 limitation:** the fuel gauge has no charging-status flag or current
measurement. Its `ALRT` output indicates low battery, not charging; see the
[MAX17043 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/max17043-max17044.pdf).
The DFR0528 board has a charging LED, but its documented MCU protocol does not
export that status. The integration therefore provides **no external-power/charging
flag, current, energy capacity or remaining time**. No extra GPIO or trend-based
charging-status estimate is used. Kernel status stays `Unknown`; UPower/desktop heuristics
may infer a state, but that is not a hardware measurement. Tested UPower 1.91.1
sets the aggregate display to `discharging` and `on-battery=yes` even though the
individual battery stays `unknown`. This can activate existing battery power
policies. Its individual-device icon is `battery-missing-symbolic`; the aggregate
DisplayDevice has the correct percentage and level icon used by the panel.
No AC power supply is
invented. This driver does not configure automatic shutdown or change the HAT's
firmware cutoff. Percentage itself is a fuel-gauge estimate, not a load test.

## Build and install on the board

Install DKMS and the headers matching `uname -r`, plus a compiler and `dtc`.
Do not force a module built for another kernel to load. Check
`/lib/modules/$(uname -r)/build` before continuing. From this directory:

```sh
make host-test
sudo install -d /usr/src/dfr0528-battery-0.1.0
sudo install -m 644 Makefile dkms.conf dfr0528_battery.c dfr0528_read.h \
    /usr/src/dfr0528-battery-0.1.0/
sudo dkms add -m dfr0528-battery -v 0.1.0
sudo dkms build -m dfr0528-battery -v 0.1.0 -k "$(uname -r)"
sudo dkms install -m dfr0528-battery -v 0.1.0 -k "$(uname -r)"
sudo install -d /boot/overlay-user
dtc -@ -I dts -O dtb -o /tmp/zero2w-dfr0528.dtbo zero2w-dfr0528.dts
sudo install -m 644 /tmp/zero2w-dfr0528.dtbo /boot/overlay-user/
```

Back up `/boot/armbianEnv.txt`. Add `i2c1-pi` to its existing `overlays` list and
`zero2w-dfr0528` to its existing `user_overlays` list, preserving all other tokens
and settings. Do not duplicate either key. Reboot, then inspect:

```sh
cat /sys/class/power_supply/dfr0528-*/uevent
upower -e
upower -d
dkms status
```

The device is registered as a system battery for the standard UPower battery
backend. It polls every five seconds and emits change events. No additional
root polling service, world-writable I²C device or private D-Bus battery is needed.
Add the **Power Manager Plugin** through XFCE panel preferences if it is absent.
It can show the UPower percentage. Its numeric
label is controlled by `xfce4-power-manager` property
`/xfce4-power-manager/show-panel-label` (`1` = percentage in XFCE 4.20).

For a temporary developer test, positively identify the adapter and PID first;
load `dfr0528_battery`, then register `dfr0528 0x10` via that adapter's
`new_device`. Do not do this if DT already created the client. Never use `-f`
I²C reads against a bound kernel driver. Unknown firmware is rejected until its
protocol is qualified.

## Removal and rollback

### Overlay manager in this fork

On Zero 2W, **System → Hardware → Device Tree Overlays → DFR0528 UPS**
provides status and next-boot enable/disable controls. The same backend is exposed
through the API:

```sh
armbian-config --api module_devicetree_overlays ups status
armbian-config --api module_devicetree_overlays ups enable
armbian-config --api module_devicetree_overlays ups disable
```

Install the DKMS driver and custom DTBO using the instructions above first; this
menu does not download/build them. Enable checks the running board, current-kernel
driver and complete composed DT, then adds `i2c1-pi` and `zero2w-dfr0528` to their
respective lists. Disable removes only the UPS user overlay and retains I²C for
other devices. The stock overlay editor/API refuses to remove `i2c1-pi` while
the UPS user overlay is enabled. Generic `show` also lists user overlays with
the `user:` prefix.

Changes are saved atomically under a shared overlay lock; before/after copies
are retained in `/boot/armbianEnv.txt.ups-backups/change.*/`. Nothing is unloaded
at runtime and the menu does not reboot automatically. Inspect status after your
next reboot. Unsupported boot routes, DT fixup parameters and conflicting
overlays are refused rather than silently dropping settings.

### Manual removal

Remove only `zero2w-dfr0528` from `user_overlays`, reboot and remove the DKMS
package with `dkms remove -m dfr0528-battery -v 0.1.0 --all`. Then remove its
source directory and `/boot/overlay-user/zero2w-dfr0528.dtbo`. Keep `i2c1-pi` if
another I²C device uses it. Restore desktop preferences from their backup if
they were changed. Avoid replacing the whole boot environment with an old copy
after unrelated changes have been made.

## Validation

`make host-test` runs the same decoder with fake reads under ASan/UBSan: known
real sample, read failures, wrong identity, torn reads, overshoot and invalid
values. It does not exercise kernel lifecycle or electrical behavior. See the
[board report](../../tests/hardware/zero2w-ups-2026-10-27.md) for actual binding,
UPower, desktop and reboot evidence and remaining limitations.
