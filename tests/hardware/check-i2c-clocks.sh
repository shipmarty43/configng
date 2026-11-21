#!/usr/bin/env bash
# Only disposable boot files. Supply the stock DTB and its stock i2c1-pi DTBO.
set -euo pipefail
[[ $# == 2 && -f $1 && -f $2 ]] || { echo "Usage: $0 ZERO2W.dtb i2c1-pi.dtbo" >&2; exit 2; }
root=$(cd "$(dirname "$0")/../.." && pwd)
script_dir="$root/bin"
declare -A module_options
for module in devicetree_overlays ups_dfr0528 sx1262_overlay spi_clocks i2c_clocks; do
    source "$root/tools/modules/system/module_$module.sh"
done
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
bootroot="$workdir/boot"
mkdir -p "$bootroot/dtb/allwinner/overlay" "$bootroot/overlay-user" "$workdir/live"
cp "$1" "$bootroot/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb"
cp "$2" "$bootroot/dtb/allwinner/overlay/sun50i-h616-i2c1-pi.dtbo"
dtc -q -@ -I dts -O dtb -o "$bootroot/overlay-user/zero2w-dfr0528.dtbo" "$root/hardware/dfrobot-ups/zero2w-dfr0528.dts"
_ups_dfr_boot() { echo "$bootroot"; }
_ups_dfr_dt() { echo "$workdir/live"; }
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$workdir/live/compatible"
printf 'armbianEnv.txt\noverlay-user/${overlay_file}.dtbo\n' > "$bootroot/boot.scr"
conf="$bootroot/armbianEnv.txt"
printf 'overlay_prefix=sun50i-h616\nrootdev=unchanged\noverlays=i2c1-pi\nuser_overlays=zero2w-dfr0528\n' > "$conf"
cp "$conf" "$workdir/before"
i2c() { module_i2c_clocks "$@"; }
reject() { if "$@"; then echo "Unexpected success: $*" >&2; exit 1; fi; }
i2c list > "$workdir/buses"
[[ $(wc -l < "$workdir/buses") == 6 ]]
grep -Eq 'twi1.*enabled.*dfrobot,dfr0528 @10' "$workdir/buses"
for hz in 400000 100000; do
    i2c set twi1 "$hz"
    _zero2w_overlay_prepare compose "$conf" "$workdir/next" clocks ''
    [[ $(fdtget -t u "$workdir/next" /soc/i2c@5002400 clock-frequency) == "$hz" ]]
    [[ $(fdtget -t u "$workdir/next" /soc/i2c@5002400/ups@10 reg) == 16 ]]
    [[ $(fdtget "$workdir/next" /soc/pinctrl@300b000/i2c1-pi-pins pins) == 'PI7 PI8' ]]
done
cp "$conf" "$workdir/saved"
i2c set twi1 100000
reject i2c set twi1 1000000
reject i2c set twi1 0
reject i2c set twi2 100000
reject _dt_overlays_write_config "$conf" false ''
cmp "$conf" "$workdir/saved"
# SPI + I2C must use the same lock, each retaining the other's override.
module_spi_clocks set spi0 0 18000000 & first=$!
i2c set twi1 400000 & second=$!
wait "$first"; wait "$second"
i2c default twi1
_zero2w_overlay_prepare compose "$conf" "$workdir/next" clocks ''
[[ $(fdtget -t u "$workdir/next" /soc/spi@5010000/flash@0 spi-max-frequency) == 18000000 ]]
! fdtget "$workdir/next" /soc/i2c@5002400 clock-frequency >/dev/null 2>&1
grep -q 'user_overlays=zero2w-dfr0528' "$conf"
module_spi_clocks default-all
cmp "$workdir/before" "$conf"
i2c set twi1 400000
id=
for folder in "$conf".i2c-clocks-backups/change.*; do
    if cmp -s "$folder/before" "$workdir/before" && cmp -s "$folder/after" "$conf"; then id=${folder##*/}; fi
done
[[ $id ]]
echo '# intervening edit' >> "$conf"
reject i2c rollback "$id"
sed -i '$d' "$conf"
i2c rollback "$id"
cmp "$workdir/before" "$conf"
echo 'PASS TWI0..4 and standby TWI, DFR0528 on PI7/PI8, 100/400 kHz, limits, SPI isolation and exact rollback'
