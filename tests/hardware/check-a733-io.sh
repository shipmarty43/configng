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
api list
api set spi2 on
reject set uart2 on
reject set i2c0 100000
api default spi2
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
echo 'PASS A733 route, clock, mode, identity, overlap and rollback checks'
