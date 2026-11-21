#!/usr/bin/env bash
# Two real DTBs, temporary boot directories, no physical GPIO, SD or firmware writes.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
[[ $# == 2 ]] || { echo 'Supply H618 and A733 distribution allwinner directories.' >&2; exit 2; }
h=$(realpath "$1"); a=$(realpath "$2")
repo=$(cd "$(dirname "$0")/../.." && pwd)
script_dir=$repo/tools; declare -A module_options
for m in devicetree_overlays ups_dfr0528 sx1262_overlay h616_uart h616_pwm spi_clocks i2c_clocks a733_io header_gpio; do
    source "$repo/tools/modules/system/module_$m.sh"
done
fixture=$(mktemp -d); trap 'rm -rf "$fixture"' EXIT
_ups_dfr_boot() { echo "$lab/boot"; }
_ups_dfr_dt() { echo "$lab/live"; }
_header_gpio_driver() { [[ $driver == yes ]]; }
_header_gpio_live() { [[ $1 == check && $live == free ]]; }
gpio() { module_header_gpio "$@"; }
reject() {
    cp "$envfile" "$lab/unchanged"
    if "$@" > "$lab/error" 2>&1; then echo "Unexpected success: $*" >&2; exit 1; fi
    cmp "$envfile" "$lab/unchanged"
}
undo() { local id=${1#*Backup: }; id=${id%%$'\n'*}; gpio rollback "${id##*/}"; }
compose() { _header_gpio_compose "$board" "$envfile" "$lab/full.dtb"; }
for board in h618 a733; do
    lab="$fixture/$board"; root="$lab/boot"; envfile="$root/armbianEnv.txt"; driver=yes; live=free
    mkdir -p "$lab/live" "$root/dtb" "$root/overlay-user"
    if [[ $board == h618 ]]; then
        ln -s "$h" "$root/dtb/allwinner"
        printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$lab/live/compatible"
        printf 'console=both\noverlay_prefix=sun50i-h616\n' > "$envfile"
        pio=/soc/pinctrl@300b000; pin=29; peer=31; initial='0 0 7 0 0 0 0 0'; expected='0 0 7 0 0 0 0 244'
    else
        ln -s "$a" "$root/dtb/allwinner"
        printf 'xunlong,orangepi-zero3w\0arm,sun60iw2p1\0' > "$lab/live/compatible"
        printf 'console=both\noverlay_prefix=sun60i-a733\nfdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\n' > "$envfile"
        pio=/soc@3000000/pinctrl@2000000; pin=37; peer=32; initial='0 0 0 0 0 8000 0 0 0 0'; expected='0 0 244000 0 0 8000 0 0 0 0'
    fi
    printf 'armbianEnv.txt\noverlay-user/${overlay_file}.dtbo\n' > "$root/boot.scr"
    printf '/dts-v1/; /plugin/; &pio { input-debounce=<%s>; };' "$initial" | dtc -q -@ -I dts -O dtb -o "$root/overlay-user/existing.dtbo"
    echo 'user_overlays=existing' >> "$envfile"
    cp "$envfile" "$lab/original"
    gpio list > "$lab/list"; [[ $(wc -l < "$lab/list") == 28 ]]
    reject gpio set 6 up 10 250
    reject gpio set 8 down default default
    reject gpio set "$pin" both 20 default
    reject gpio set "$pin" up 15 default
    reject gpio set "$pin" default default 4000000
    driver=no
    reject gpio set "$pin" up 20 default
    gpio set "$pin" default default 244
    gpio default "$pin"
    grep -Fx 'user_overlays=existing' "$envfile"
    driver=yes; live=busy
    reject gpio set "$pin" off 20 default
    live=free
    change=$(gpio set "$pin" up 20 244)
    [[ $(gpio get "$pin") == 'up 20 244' ]]
    compose
    [[ $(fdtget -t u "$lab/full.dtb" "/opi-header-gpio-$pin" drive-strength) == 20 ]]
    fdtget "$lab/full.dtb" "/opi-header-gpio-$pin" bias-pull-up
    [[ $(fdtget -t u "$lab/full.dtb" "$pio" input-debounce) == "$expected" ]]
    cp "$envfile" "$lab/one"
    gpio verify
    # An overlay loaded later must not overwrite the complete bank vector.
    printf '/dts-v1/; /plugin/; &pio { input-debounce=<%s>; };' "$initial" | dtc -q -@ -I dts -O dtb -o "$root/overlay-user/override-bank.dtbo"
    sed -i '/^user_overlays=/s/$/ override-bank/' "$envfile"
    reject gpio verify
    cp "$lab/one" "$envfile"
    gpio set "$peer" down 40 244
    reject gpio set "$peer" down 40 122
    gpio default "$pin"; compose
    [[ $(fdtget -t u "$lab/full.dtb" "$pio" input-debounce) == "$expected" ]]
    gpio default "$peer"; compose
    [[ $(fdtget -t u "$lab/full.dtb" "$pio" input-debounce) == "$initial" ]]
    cmp "$envfile" "$lab/original"
    gpio set "$pin" up 20 244
    msg=$(gpio set "$pin" off 30 default)
    compose; fdtget "$lab/full.dtb" "/opi-header-gpio-$pin" bias-disable
    echo '# unrelated change' >> "$envfile"; reject undo "$msg"
    sed -i '$d' "$envfile"
    driver=no; reject undo "$msg"; driver=yes
    undo "$msg"; cmp "$envfile" "$lab/one"
    undo "$change"; cmp "$envfile" "$lab/original"
    gpio set "$pin" default 10 default
    msg=$(gpio default "$pin")
    tac "$envfile" > "$lab/reordered"; cp "$lab/reordered" "$envfile"
    undo "$msg"
    [[ $(gpio get "$pin") == 'default 10 default' ]]
    gpio default "$pin"
    if [[ $board == h618 ]]; then
        reject gpio set 36 default default 100  # PMIC IRQ on PC9 affects PC12
        grep -q 'pmic' "$lab/error"
        gpio set 3 up default default
        reject _dt_overlays_write_config "$envfile" false i2c1-pi
        reject module_h616_uart enable-rtscts uart2
        gpio default 3
        _dt_overlays_write_config "$envfile" false i2c1-pi
        reject gpio set 3 off 20 default
        _dt_overlays_write_config "$envfile" false ''
        gpio set 32 down 20 default
        reject _dt_overlays_write_config "$envfile" false pwm1-pi11
    else
        reject gpio set 3 default default 244  # vendor pin-test IRQ on PB6
        grep -q 'pinctrl_test' "$lab/error"
        gpio set 3 up default default
        reject module_a733_io set i2c0 400000
        reject module_a733_io set uart2 rtscts
        gpio default 3
        module_a733_io set i2c0 400000
        reject gpio set 5 down 10 default
        module_a733_io default i2c0
        gpio set 16 down 30 default; compose
        rpio=/soc@3000000/pinctrl@7025000
        handle=$(fdtget -t u "$lab/full.dtb" "$rpio" phandle)
        [[ $(fdtget -t u "$lab/full.dtb" /opi-header-gpio-16 target-gpios) == "$handle 0 2 0" ]]
        reject gpio set 16 down 30 100  # external Type-C IRQ on PL9
        grep -q husb311 "$lab/error"
        # Fixture frees the PL IRQ to exercise the separate two-cell standby bank.
        printf '/dts-v1/; /plugin/; &{/soc@3000000/twi@7084000/husb311@22} { status="disabled"; };' | dtc -q -@ -I dts -O dtb -o "$root/overlay-user/fixture-pl.dtbo"
        sed -i '/^user_overlays=/s/$/ fixture-pl/' "$envfile"
        gpio set 16 down 30 61; compose
        [[ $(fdtget -t u "$lab/full.dtb" "$rpio" input-debounce) == '61000 0' ]]
        [[ $(fdtget -t u "$lab/full.dtb" "$pio" input-debounce) == "$initial" ]]
        reject module_a733_io set uart7 on
        gpio set 7 off 10 default
        reject _dt_overlays_write_config "$envfile" false pwm0
        reject module_a733_io add-cs 1
    fi
    echo "PASS $board: 28 physical GPIOs, pad and bank conflicts, persistence and exact rollback"
done
