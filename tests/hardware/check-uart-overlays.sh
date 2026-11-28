#!/usr/bin/env bash
# Use an image's original DTB and stock overlay directory; write only in a temporary directory.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
[[ $# == 2 ]] || { echo "Usage: $0 ZERO2W.dtb STOCK_OVERLAY_DIR" >&2; exit 2; }
root=$(cd "$(dirname "$0")/../.." && pwd)
script_dir="$root/bin"; declare -A module_options
for module in devicetree_overlays ups_dfr0528 sx1262_overlay spi_clocks i2c_clocks h616_uart; do
    source "$root/tools/modules/system/module_$module.sh"
done
temp=$(mktemp -d); trap 'rm -rf "$temp"' EXIT
bootroot="$temp/boot"; conf="$bootroot/armbianEnv.txt"; dt="$bootroot/dtb/allwinner"
mkdir -p "$dt/overlay" "$bootroot/overlay-user" "$temp/live"
cp "$1" "$dt/sun50i-h618-orangepi-zero2w.dtb"
for ov in i2c4-ph i2c0-pi i2c1-pi i2c2-pi pwm1-pi11 pwm2-pi12 pwm3-pi13 pwm2-ph2 uart2-pi uart3-pi uart4-pi uart5 uart2-pi-rts-cts; do
    cp "$2/sun50i-h616-$ov.dtbo" "$dt/overlay/"
done
dtc -q -@ -I dts -O dtb -o "$bootroot/overlay-user/zero2w-dfr0528.dtbo" "$root/hardware/dfrobot-ups/zero2w-dfr0528.dts"
_ups_dfr_boot() { echo "$bootroot"; }
_ups_dfr_dt() { echo "$temp/live"; }
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$temp/live/compatible"
printf 'armbianEnv.txt\noverlay-user/${overlay_file}.dtbo\n' > "$bootroot/boot.scr"
printf 'overlay_prefix=sun50i-h616\nrootdev=keep\noverlays=i2c1-pi pwm1-pi11\nuser_overlays=zero2w-dfr0528\n' > "$conf"
cp "$conf" "$temp/original"
api() { module_h616_uart "$@"; }
reject() { if "$@"; then echo "Unexpected success: $*" >&2; exit 1; fi; }
for n in 2 3 4 5; do api enable "uart$n"; done
api routes > "$temp/routes"
[[ $(grep -c 'managed, enabled' "$temp/routes") == 4 ]]
cp "$conf" "$temp/all"
api enable uart4
cmp "$conf" "$temp/all"
for other in i2c0-pi i2c2-pi pwm3-pi13 pwm2-ph2 uart2-pi-rts-cts; do
    reject _dt_overlays_write_config "$conf" false "i2c1-pi pwm1-pi11 $other"
    cmp "$conf" "$temp/all"
done
# Check GPIO consumers that declare gpios rather than a pinctrl group.
printf '/dts-v1/; /plugin/; &{/} { test-keys { compatible="gpio-keys"; button { gpios=<&pio 8 10 0>; }; }; };\n' > "$temp/keys.dts"
dtc -q -@ -I dts -O dtb -o "$dt/overlay/sun50i-h616-keys.dtbo" "$temp/keys.dts"
reject _dt_overlays_write_config "$conf" false 'i2c1-pi pwm1-pi11 keys'
reject api disable uart0
api disable uart3
id=
for dir in "$conf".uart-backups/change.*; do
    if cmp -s "$dir/after" "$conf" && cmp -s "$dir/before" "$temp/all"; then id=${dir##*/}; fi
done
[[ $id ]]
echo '# manual edit' >> "$conf"; reject api boot-rollback "$id"
sed -i '$d' "$conf"; api boot-rollback "$id"; cmp "$conf" "$temp/all"
# The faulty stock UART4 overlay targets UART3. Replace only its named token.
cp "$temp/original" "$conf"
sed -i 's/^overlays=.*/& uart4-pi/' "$conf"
api enable uart4
_zero2w_overlay_prepare compose "$conf" "$temp/next" uart ''
[[ $(fdtget "$temp/next" /soc/serial@5000c00 status) == disabled ]]
[[ $(fdtget "$temp/next" /soc/serial@5001000 status) == okay ]]
[[ $(fdtget "$temp/next" /soc/pinctrl@300b000/opi-uart4-header-pins function) == uart4 ]]
[[ $(fdtget "$temp/next" /soc/i2c@5002400/ups@10 compatible) == dfrobot,dfr0528 ]]
[[ $(fdtget "$temp/next" /soc/serial@5000000 status) == okay ]]
api disable uart4
cmp "$conf" "$temp/original"
# Opposite transaction order must also refuse sharing the pins.
sed -i 's/^overlays=.*/& i2c2-pi/' "$conf"
cp "$conf" "$temp/conflict"
reject api enable uart3; cmp "$conf" "$temp/conflict"
# On the stock image the boot quirk hook removes/re-appends the same setting.
cp "$temp/original" "$conf"
echo 'usbstoragequirks=test:fixture:u' >> "$conf"
cp "$conf" "$temp/quirks-before"
api enable uart3
id=
for dir in "$conf".uart-backups/change.*; do
    if cmp -s "$dir/after" "$conf" && cmp -s "$dir/before" "$temp/quirks-before"; then id=${dir##*/}; fi
done
[[ $id ]]
sed -i '/^usbstoragequirks=/d' "$conf"
echo 'usbstoragequirks=test:fixture:u' >> "$conf"
api boot-rollback "$id"; cmp "$conf" "$temp/quirks-before"
# Exercise safe feedback in both directions: the DFR0528 bus uses the PI handshake pair.
cp "$temp/original" "$conf"
cp "$conf" "$temp/unchanged-flow"
reject api enable-rs485 uart2
reject api enable-rtscts uart2
cmp "$temp/unchanged-flow" "$conf"
api enable-rs485-ph uart2
_zero2w_overlay_prepare compose "$conf" "$temp/de.dtb" uart ''
fdtget "$temp/de.dtb" /soc/serial@5000800 armbian-config,rs485-de | grep -Fx h618
api enable-rtscts-ph uart2
api routes | grep 'uart2.*24/23/19/21.*managed, enabled'
_zero2w_overlay_prepare compose "$conf" "$temp/ph-flow.dtb" uart ''
python3 -B "$root/tests/hardware/check-uart-flow.py" h618 uart2 "$temp/ph-flow.dtb"
reject _dt_overlays_write_config "$conf" false 'i2c1-pi pwm1-pi11 i2c4-ph'
api disable uart2
reject api enable-rtscts uart3  # PWM1 already owns PI11
reject api enable-rtscts uart5
reject api enable-rtscts-ph uart4
cp "$temp/original" "$conf"
sed -i -e 's/^overlays=.*/overlays=/' -e 's/^user_overlays=.*/user_overlays=/' "$conf"
for n in 2 3 4; do api enable-rtscts "uart$n"; done
api routes | grep 'uart2.*15/22/5/3.*managed, enabled'
api routes | grep 'uart3.*28/27/32/33.*managed, enabled'
api routes | grep 'uart4.*7/16/31/37.*managed, enabled'
_zero2w_overlay_prepare compose "$conf" "$temp/flow.dtb" uart ''
for n in 2 3 4; do
    addr=$(printf '%x' "$((0x5000000 + n * 0x400))")
    [[ $(fdtget "$temp/flow.dtb" "/soc/serial@$addr" armbian-config,rtscts) == h618 ]]
    fdtget "$temp/flow.dtb" "/soc/serial@$addr" uart-has-rtscts
    python3 -B "$root/tests/hardware/check-uart-flow.py" h618 "uart$n" "$temp/flow.dtb"
done
cp "$conf" "$temp/flow-before"
printf '/dts-v1/; /plugin/; &uart3 {linux,rs485-enabled-at-boot-time;};' |
    dtc -q -@ -I dts -O dtb -o "$dt/overlay/sun50i-h616-conflicting-rs485.dtbo"
reject _dt_overlays_write_config "$conf" false conflicting-rs485
cmp "$conf" "$temp/flow-before"
for other in i2c1-pi pwm1-pi11 pwm2-pi12 pwm3-pi13; do
    reject _dt_overlays_write_config "$conf" false "$other"
    cmp "$conf" "$temp/flow-before"
done
msg=$(api enable uart3)
id=${msg#*Backup: }; id=${id%%$'\n'*}
api routes | grep 'uart3.*TX/RX 28/27; managed, enabled'
api boot-rollback "${id##*/}"
cmp "$conf" "$temp/flow-before"
echo 'PASS all four header routes, stock UART4 correction, pin conflicts in both directions, GPS/UPS/PWM coexistence and rollback'
