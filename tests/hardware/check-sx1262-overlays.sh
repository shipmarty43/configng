#!/usr/bin/env bash
# Offline integration with the exact board DTB and installed/user DTBOs.
set -eu
if [[ $# -ne 5 ]]; then
    echo "Usage: $0 base.dtb i2c1-pi.dtbo pwm1-pi11.dtbo zero2w-dfr0528.dtbo opi-zero2w-sx1262.dtbo" >&2
    exit 2
fi
repo=$(cd "$(dirname "$0")/../.." && pwd)
script_dir="$repo/bin"
declare -A module_options
source "$repo/tools/modules/system/module_devicetree_overlays.sh"
source "$repo/tools/modules/system/module_ups_dfr0528.sh"
source "$repo/tools/modules/system/module_sx1262_overlay.sh"
testroot=$(mktemp -d)
trap 'rm -rf "$testroot"' EXIT
bootroot="$testroot/boot"
mkdir -p "$bootroot/dtb/allwinner/overlay" "$bootroot/overlay-user" "$testroot/dt" "$testroot/class"
_ups_dfr_boot() { echo "$bootroot"; }
_ups_dfr_dt() { echo "$testroot/dt"; }
_sx1262_class() { echo "$testroot/class"; }
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$testroot/dt/compatible"
printf 'armbianEnv.txt\noverlay-user/${overlay_file}.dtbo\n' > "$bootroot/boot.scr"
cp "$1" "$bootroot/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb"
cp "$2" "$bootroot/dtb/allwinner/overlay/sun50i-h616-i2c1-pi.dtbo"
cp "$3" "$bootroot/dtb/allwinner/overlay/sun50i-h616-pwm1-pi11.dtbo"
cp "$4" "$bootroot/overlay-user/zero2w-dfr0528.dtbo"
cp "$5" "$bootroot/overlay-user/opi-zero2w-sx1262.dtbo"
envfile="$bootroot/armbianEnv.txt"
printf 'rootdev=UUID=test\noverlay_prefix=sun50i-h616\noverlays=i2c1-pi pwm1-pi11\nuser_overlays=zero2w-dfr0528\n' > "$envfile"
cp "$envfile" "$testroot/original"
radio() { module_devicetree_overlays sx1262 "$@"; }
radio enable
radio enable
radio status | grep -q 'Next boot: enabled'
radio status | grep -q 'Live SPI endpoint: unbound'
mkdir -p "$testroot/class/spidev7.0/device" "$testroot/dt/soc/spi@5011000/radio@0"
ln -s "$testroot/dt/soc/spi@5011000/radio@0" "$testroot/class/spidev7.0/device/of_node"
radio status | grep -q 'Live SPI endpoint: /dev/spidev7.0'
backups=("$envfile".sx1262-backups/change.*)
[[ ${#backups[@]} == 1 ]]
backup=${backups[0]##*/}
cp "$envfile" "$testroot/enabled"
printf '/dts-v1/; /plugin/; &spi1 { #address-cells=<1>; #size-cells=<0>; spidev@0 { reg=<0>; compatible="armbian,spi-dev"; }; };\n' > "$testroot/conflict.dts"
dtc -q -@ -I dts -O dtb -o "$bootroot/dtb/allwinner/overlay/sun50i-h616-conflict.dtbo" "$testroot/conflict.dts"
if _dt_overlays_write_config "$envfile" false 'i2c1-pi pwm1-pi11 conflict'; then exit 1; fi
cmp "$envfile" "$testroot/enabled"
echo '# manual edit' >> "$envfile"
if radio rollback "$backup"; then exit 1; fi
grep -qx '# manual edit' "$envfile"
cp "$testroot/enabled" "$envfile"
radio rollback "$backup"
cmp "$envfile" "$testroot/original"
radio enable
radio disable
cmp "$envfile" "$testroot/original"
sed -i 's/pwm1-pi11/pwm1-pi11 conflict/' "$envfile"
cp "$envfile" "$testroot/conflict"
if radio enable; then exit 1; fi
cmp "$envfile" "$testroot/conflict"
echo 'PASS: compose, idempotence, live/boot status, SPI collision, rollback and disable with UPS/PWM retained'
