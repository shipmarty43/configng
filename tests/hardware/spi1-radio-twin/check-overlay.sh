#!/bin/bash
# Validate transitions and conflicting pin owners using a disposable copy of /boot.
set -euo pipefail
[[ $# == 2 ]] || { echo "Usage: $0 BOARD_DTB_DIR SINGLE_HAT.dtbo" >&2; exit 2; }
dt=$(realpath "$1"); single=$(realpath "$2"); repo=$(cd "$(dirname "$0")/../../.." && pwd)
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
script_dir=$repo/bin; declare -A module_options
for m in devicetree_overlays sx1262_overlay ups_dfr0528 spi_clocks; do source "$repo/tools/modules/system/module_$m.sh"; done
_ups_dfr_boot() { echo "$w/b"; }; _ups_dfr_dt() { echo "$w/live"; }; _sx1262_class() { echo "$w/class"; }
mkdir -p "$w/b/dtb" "$w/b/overlay-user" "$w/live" "$w/class"; ln -s "$dt" "$w/b/dtb/allwinner"
envfile="$w/b/armbianEnv.txt"; folder="$w/b/overlay-user"
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$w/live/compatible"
printf '%s\n' 'armbianEnv.txt overlay-user/${overlay_file}.dtbo' > "$w/b/boot.scr"
printf 'rootdev=UUID=fixture\noverlay_prefix=sun50i-h616\noverlays=i2c1-pi pwm1-pi11\n' > "$envfile"
cp "$single" "$folder/opi-zero2w-sx1262.dtbo"; cp "$envfile" "$w/before"
radio() { module_sx1262_overlay "$@"; }
reject() { cp "$envfile" "$w/check"; if "$@" > "$w/error" 2>&1; then echo "Unexpected success: $*" >&2; exit 1; fi; cmp "$envfile" "$w/check"; }
backup() { sed -n 's@.*Backup: .*/\(change\.[[:alnum:]]*\).*@\1@p'; }

radio enable; cp "$envfile" "$w/single"
change=$(radio shared | backup); cp "$envfile" "$w/shared"
radio shared | grep 'already matches'
! grep -q 'opi-zero2w-sx1262' "$envfile"
radio status | grep -F 'CS2, pin 24'
radio rollback "$change"; cmp "$envfile" "$w/single"
radio shared; cmp "$envfile" "$w/shared"
# Repeated switches are atomic and independent of unrelated assignments.
radio enable; cmp "$envfile" "$w/single"
radio shared; radio disable; ! grep -q 'opi-zero2w-' "$envfile"
cp "$w/before" "$envfile"
# Foreign providers must also be rejected when the shared overlay is applied LAST.
printf '/dts-v1/;/plugin/;&spi1 {status="okay"; radio@0 {reg=<0>;compatible="test,other";};};' |
    dtc -q -@ -o "$folder/foreign.dtbo"
echo 'user_overlays=foreign' >> "$envfile"; reject radio shared
grep -q 'already enables SPI1' "$w/error"
# Each chip select and each fixed sideband is checked against foreign GPIO consumers.
for spec in '8 3' '7 9' '7 5' '7 4' '8 1' '8 4' '2 12' '8 15'; do
    printf '/dts-v1/;/plugin/;/ {fragment@0 {target-path="/"; __overlay__ {occupier { test-gpios=<&pio %s 0>; };};};};' "$spec" |
        dtc -q -@ -o "$folder/foreign.dtbo"
    reject radio shared; grep -q 'conflicting owners' "$w/error"
done
cp "$w/shared" "$envfile"
module_spi_clocks set spi1 1 1000000; module_spi_clocks set spi1 2 4000000
reject radio disable
module_spi_clocks default spi1 1; module_spi_clocks default spi1 2
radio disable
echo 'PASS radio selection, conflicts on all eight pads, provider ownership, per-CS clocks and rollback'
