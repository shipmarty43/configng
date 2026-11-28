#!/usr/bin/env bash
# Argument is the extracted DT package's allwinner directory.
set -euo pipefail
vendor=$(realpath "${1:?supply directory containing sun60i-a733-orangepi-zero3w.dtb}")
repo=$(cd "$(dirname "$0")/../.." && pwd)
fixture_dir=$(mktemp -d)
trap 'rm -rf "$fixture_dir"' EXIT
export PYTHONDONTWRITEBYTECODE=1
declare -A module_options
source "$repo/tools/modules/system/module_ups_dfr0528.sh"
source "$repo/tools/modules/system/module_devicetree_overlays.sh"
source "$repo/tools/modules/system/module_a733_io.sh"
script_dir=$repo/tools
root="$fixture_dir/boot"
mkdir -p "$root/dtb" "$fixture_dir/live"
ln -s "$vendor" "$root/dtb/allwinner"
printf '%s\0' xunlong,orangepi-zero3w arm,sun60iw2p1 > "$fixture_dir/live/compatible"
printf '%s\n' 'armbianEnv.txt' 'overlay-user/${overlay_file}.dtbo' > "$root/boot.scr"
_ups_dfr_boot() { echo "$fixture_dir/boot"; }
_ups_dfr_dt() { echo "$fixture_dir/live"; }
envfile="$root/armbianEnv.txt"
printf 'console=both\nfdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\noverlay_prefix=sun60i-a733\n' > "$envfile"
api() { module_a733_io "$@"; }
reject() {
    cp "$envfile" "$fixture_dir/check"
    if api "$@" >"$fixture_dir/rejection" 2>&1; then echo "Unexpected success: $*" >&2; exit 1; fi
    cmp "$envfile" "$fixture_dir/check"
}
compose_current() {
    PYTHONPATH="$repo/share/armbian-config" python3 -B - "$root" "$envfile" "$fixture_dir/composed.dtb" <<'PYDT'
from pathlib import Path
import sys
from a733_io import compose
root, env, output = map(Path, sys.argv[1:])
compose(root, env.read_text(), output)
PYDT
}
api list
api set spi2 on
reject set spi2-cs0 400000 0
printf '/dts-v1/; /plugin/; &spi2 { sensor@0 {reg=<0>; compatible="test,bench-sensor"; spi-max-frequency=<8000000>; }; };' | dtc -q -@ -I dts -O dtb -o "$root/overlay-user/bench-sensor.dtbo"
sed -i '/^user_overlays=/s/$/ bench-sensor/' "$envfile"
api set spi2-cs0 2000000 2
api list | grep -F 'sensor@0 2000000 Hz mode 2'
reject set spi2-cs0 8000001 1
api default spi2-cs0
reject set uart2 on
reject set i2c0 100000
api default spi2
# Native selects can be sparse. Selecting CS3 must leave CS1/PB4 available to PWM0.
reject add-cs 3
grep -q 'PB6.*pinctrl_test' "$fixture_dir/rejection"
api set pinctrl-test release
api add-cs 3
compose_current
sp=/soc@3000000/spi@2542000
gp=/soc@3000000/pinctrl@2000000
[[ $(fdtget -t u "$fixture_dir/composed.dtb" "$sp" sunxi,spi-num-cs) == 4 ]]
[[ $(fdtget "$fixture_dir/composed.dtb" "$gp/opi-spi2-pins" pins) == 'PB0 PB1 PB2 PB3 PB6' ]]
reject default pinctrl-test
api list | grep 'spi2.*CS3 pin 35'
_dt_overlays_write_config "$envfile" false 'pwm0'
reject add-cs 1
grep -q 'PB4 also claimed' "$fixture_dir/rejection"
_dt_overlays_write_config "$envfile" false ''
api add-cs 1
# The stock PWM1 uses PD1; the documented PB5 alternate collides only with CS2.
printf '/dts-v1/; /plugin/; &pwm0_1_pins_active {pins="PB5";}; &pwm0_1_pins_sleep {pins="PB5";}; &pwm0_1 {status="okay";};' |
    dtc -q -@ -I dts -O dtb -o "$root/overlay-user/test-pwm1-pb5.dtbo"
sed -i '/^user_overlays=/s/$/ test-pwm1-pb5/' "$envfile"
reject add-cs 2
grep -q 'PB5 also claimed' "$fixture_dir/rejection"
sed -i 's/ test-pwm1-pb5//' "$envfile"
api add-cs 2
compose_current
for group in opi-spi2-pins opi-spi2-sleep; do
    [[ $(fdtget "$fixture_dir/composed.dtb" "$gp/$group" pins) == 'PB0 PB1 PB2 PB3 PB4 PB5 PB6' ]]
done
cp "$envfile" "$fixture_dir/four-cs"
if _dt_overlays_write_config "$envfile" false pwm8; then exit 1; fi
cmp "$envfile" "$fixture_dir/four-cs"
reject set i2c0 400000
reject add-cs 4
# Declare three synthetic endpoints on the genuine controller. Each ceiling is independent.
printf '/dts-v1/; /plugin/; &spi2 { sensor@1 {reg=<1>; compatible="test,cs1"; spi-max-frequency=<1000000>;}; sensor@2 {reg=<2>;compatible="test,cs2";spi-max-frequency=<2000000>;}; sensor@3 {reg=<3>;compatible="test,cs3";spi-max-frequency=<4000000>;};};' |
    dtc -q -@ -I dts -O dtb -o "$root/overlay-user/test-extra-clients.dtbo"
sed -i '/^user_overlays=/s/$/ test-extra-clients/' "$envfile"
for cs in 1 2 3; do api set "spi2-cs$cs" "$((cs * 500000))" "$cs"; done
status=$(api list)
for cs in 1 2 3; do
    grep -F "CS$cs sensor@$cs $((cs * 500000)) Hz mode $cs" <<< "$status"
    reject remove-cs "$cs"
done
reject set spi2-cs1 1000001 1
cp "$envfile" "$fixture_dir/before-cs-change"
msg=$(api set spi2-cs2 250000 0)
backup=${msg#*Backup: }; backup=${backup%%$'\n'*}
api rollback "${backup##*/}"
cmp "$fixture_dir/before-cs-change" "$envfile"
for cs in 1 2 3; do api default "spi2-cs$cs"; done
reject remove-cs 1  # an enabled CS1 client still needs the physical pin
sed -i 's/ test-extra-clients//' "$envfile"
api remove-cs 1
api remove-cs 2
api remove-cs 3
api default pinctrl-test
api default spi2
# The shared stock overlay editor must also guard the reverse order of UART/TWI changes.
api set uart2 rtscts
compose_current
python3 -B "$repo/tests/hardware/check-uart-flow.py" a733 uart2 "$fixture_dir/composed.dtb"
api list | grep 'uart2.*RTS/CTS 5/3'
reject set i2c0 100000
cp "$envfile" "$fixture_dir/with-flow"
if _dt_overlays_write_config "$envfile" false i2c0; then exit 1; fi
cmp "$envfile" "$fixture_dir/with-flow"
msg=$(api set uart2 on)
backup=${msg#*Backup: }; backup=${backup%%$'\n'*}
api list | grep 'uart2.*enabled' | grep -vq RTS/CTS
api rollback "${backup##*/}"
cmp "$envfile" "$fixture_dir/with-flow"
api default uart2
api set i2c0 100000
reject set uart2 rtscts
api set uart2 on  # its TX/RX alone use PB0/1
api default uart2
api default i2c0
reject set uart6 rtscts  # camera MCLK owns PE0
api set camera release
# PE3 is also a legal alternate pad for PWM0. Start with two-wire UART6.
api set uart6 on
printf '/dts-v1/; /plugin/; &pwm0_0_pins_active {pins="PE3";}; &pwm0_0_pins_sleep {pins="PE3";}; &pwm0_0 {status="okay";};' |
    dtc -q -@ -I dts -O dtb -o "$root/overlay-user/test-pwm0-pe3.dtbo"
sed -i '/^user_overlays=/s/$/ test-pwm0-pe3/' "$envfile"
reject set uart6 rtscts
grep -q 'PE3 also claimed' "$fixture_dir/rejection"
sed -i 's/ test-pwm0-pe3//' "$envfile"
reject set uart6 rs485
api set uart6 rtscts
compose_current
python3 -B "$repo/tests/hardware/check-uart-flow.py" a733 uart6 "$fixture_dir/composed.dtb"
api list | grep 'uart6.*RTS/CTS 19/21'
reject set i2c3 100000
reject set spi3-cs0 500000 0
api set uart6 on  # PE3 is free on the two-wire route
api set i2c3 400000
reject set uart6 rtscts
api default i2c3
api default uart6
api default camera
reject set uart7 rtscts
reject set spi3-cs0 187499 0
reject set spi3-cs0 500000 0
grep -q 'PE0.*vind' "$fixture_dir/rejection"
api set camera release
api set spi3-cs0 8000000 3
# Test alternate CS wiring, duplicate bindings and IRQ-only pin owners.
for spec in cs duplicate irq; do
    case $spec in
        cs) source='&spi3 { cs-gpios = <&pio 1 5 1>, <0>; };' ;;
        duplicate) source='&spi3 { extra@0 { reg=<0>; compatible="test,client"; }; };' ;;
        irq) source='/ { fragment@0 { target-path="/"; __overlay__ { client { interrupt-parent=<&pio>; interrupts=<1 2 1>; }; }; }; };' ;;
    esac
    printf '/dts-v1/; /plugin/; %s\n' "$source" | dtc -q -@ -I dts -O dtb -o "$root/overlay-user/check-$spec.dtbo"
    cp "$envfile" "$fixture_dir/no-injection"
    sed -i "/^user_overlays=/s/$/ check-$spec/" "$envfile"
    reject set i2c0 100000
    case $spec in
        cs) grep -q 'native master chip selects' "$fixture_dir/rejection" ;;
        duplicate) grep -q 'Duplicate or invalid chip select' "$fixture_dir/rejection" ;;
        irq) grep -q 'PB2 also claimed' "$fixture_dir/rejection" ;;
    esac
    cp "$fixture_dir/no-injection" "$envfile"
done
# Both controllers and two real DT endpoints must coexist and roll back independently.
api set spi2 on
api set spi2-cs0 1000000 2
compose_current
[[ $(fdtget -t u "$fixture_dir/composed.dtb" /soc@3000000/spi@2542000/sensor@0 spi-max-frequency) == 1000000 ]]
[[ $(fdtget -t u "$fixture_dir/composed.dtb" /soc@3000000/spi@2543000/spidev@0 spi-max-frequency) == 8000000 ]]
api default spi2-cs0
api default spi2
api set spi3-cs1 250000 1
api list | grep -F 'CS0 8000000 Hz mode 3, CS1 250000 Hz mode 1'
reject set i2c2 100000
reject set uart6 on
reject default camera
reject set spi3-cs0 100000001 0
reject set spi3-cs1 100000 4
api set i2c0 100000
api set i2c1 400000
api set uart2 on
api set uart7 on
reject set i2c0 1000000
reject set uart1 on
cp "$envfile" "$fixture_dir/before-uart"
message=$(api default uart2)
backup=$(basename "$(find "$root/armbianEnv.txt.a733-io-backups" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)")
api rollback "$backup"
cmp "$envfile" "$fixture_dir/before-uart"
api default uart2
backup=$(basename "$(find "$root/armbianEnv.txt.a733-io-backups" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)")
# A boot helper may reorder assignments without changing any value.
tac "$envfile" > "$fixture_dir/reordered"
cp "$fixture_dir/reordered" "$envfile"
api rollback "$backup"
diff <(sort "$fixture_dir/before-uart") <(sort "$envfile")
api default spi3-cs0
api default spi3-cs1
api set uart6 on
api default uart6
api default camera
api set i2c2 400000
api set i2c3 100000
api list
echo overlays=uart6 >> "$envfile"
reject set spi3-cs0 500000 0
printf '%s\0' xunlong,orangepi-4-pro arm,sun60iw2p1 > "$fixture_dir/live/compatible"
reject set uart2 on
echo 'PASS A733 four native SPI2 selects, two UART handshake routes, pin exclusions and rollback'
