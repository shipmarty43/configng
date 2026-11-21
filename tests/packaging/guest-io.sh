#!/usr/bin/env bash
# This script is run only on the test VM with its own qcow2 boot partition.
set -euo pipefail
shared=/opt/armbian-config-zero2w/share/armbian-config
boot=/boot/armbianEnv.txt
test -e /mnt/opi-release/io-current
! grep -Eq '^(overlays|user_overlays)=' "$boot" || exit 1
mkdir -p /boot/overlay-user
dtc -q -@ -I dts -O dtb -o /boot/overlay-user/zero2w-dfr0528.dtbo /mnt/opi-release/zero2w-dfr0528.dts
printf 'overlays=i2c1-pi\nuser_overlays=zero2w-dfr0528\n' >> "$boot"
cp "$boot" /run/baseline-io.env
armbian-config-zero2w --api module_i2c_clocks set twi1 400000
name=$(awk '/^user_overlays=/{print $2}' "$boot")
test "$name" = opi-twi-clock-twi1-400000
fdtoverlay -i /boot/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb -o /run/next.dtb \
    /boot/dtb/allwinner/overlay/sun50i-h616-i2c1-pi.dtbo /boot/overlay-user/{zero2w-dfr0528,$name}.dtbo
test "$(fdtget -t u /run/next.dtb /soc/i2c@5002400 clock-frequency)" = 400000
test "$(fdtget /run/next.dtb /soc/i2c@5002400/ups@10 compatible)" = dfrobot,dfr0528
backup=(/boot/armbianEnv.txt.i2c-clocks-backups/change.*)
armbian-config-zero2w --api module_i2c_clocks rollback "${backup[0]##*/}"
cmp "$boot" /run/baseline-io.env
systemd-analyze verify opi-zero2w-pwm.service
if systemctl is-active --quiet opi-zero2w-pwm.service; then exit 1; fi
python3 "$shared/h616_pwm.py" set 20000 37.5 inversed
python3 "$shared/h616_pwm.py" status | grep -F '20000 Hz, 37.5% active'
python3 "$shared/h616_pwm.py" default
test ! -e /etc/armbian-config/pwm1.json
PYTHONPATH="$shared" python3 /mnt/opi-release/guest-uart.py
python3 guest_menu.py I2C001 'Select a physical bus'
if [[ -f $shared/pwm_routes.py ]]; then
    python3 guest_menu.py PWM001 'Choose a channel'
else
    python3 guest_menu.py PWM001 'Save frequency'
fi
echo PASS-H616-PACKAGES
