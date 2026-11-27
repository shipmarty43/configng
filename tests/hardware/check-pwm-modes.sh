#!/usr/bin/env bash
# Compose both distribution DTBs against scratch boot directories.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
[[ $# == 2 ]] || { echo 'Supply the H618 and A733 allwinner DTB directories.' >&2; exit 2; }
h=$(realpath "$1"); a=$(realpath "$2")
repo=$(cd "$(dirname "$0")/../.." && pwd)
script_dir=$repo/tools; declare -A module_options
for m in devicetree_overlays ups_dfr0528 h616_uart h616_pwm a733_io header_gpio pwm_modes; do
    source "$repo/tools/modules/system/module_$m.sh"
done
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
_ups_dfr_boot() { echo "$lab/boot"; }
_ups_dfr_dt() { echo "$lab/live"; }
pwm() { module_pwm_modes "$@"; }
reject() { cp "$envfile" "$lab/before"; if "$@"; then echo "Unexpected success: $*" >&2; exit 1; fi; cmp "$envfile" "$lab/before"; }
undo() { local id=${1#*Backup: }; id=${id%%$'\n'*}; pwm rollback "${id##*/}"; }
for board in h618 a733; do
    lab="$work/$board"; root="$lab/boot"; envfile="$root/armbianEnv.txt"
    mkdir -p "$lab/live" "$root/dtb" "$root/overlay-user"
    printf 'armbianEnv.txt\noverlay-user/${overlay_file}.dtbo\n' > "$root/boot.scr"
    if [[ $board == h618 ]]; then
        ln -s "$h" "$root/dtb/allwinner"
        printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$lab/live/compatible"
        printf 'overlay_prefix=sun50i-h616\nconsole=both\nuser_overlays=\n' > "$envfile"
        reject pwm set pair 2 500
        echo 'overlays=pwm2-pi12 pwm3-pi13' >> "$envfile"
        first=2; node=/soc/pwm2@0300a000
        reject pwm set burst 2 7; reject pwm set capture 2; reject pwm set fan 5 0 50 100 170 255
    else
        ln -s "$a" "$root/dtb/allwinner"
        printf 'xunlong,orangepi-zero3w\0arm,sun60iw2p1\0' > "$lab/live/compatible"
        printf 'overlay_prefix=sun60i-a733\nfdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\nuser_overlays=\n' > "$envfile"
        first=0; node=/soc@3000000/pwm0@2527010
        reject pwm set pair 8 500   # PB6 is used by pinctrl_test
        reject pwm set burst 4 17   # PWM0-5 is the fan
    fi
    cp "$envfile" "$lab/original"
    reject pwm set pair "$first" 41; reject pwm set pair "$first" 10667
    change=$(pwm set pair "$first" 500)
    pwm verify
    _header_gpio_compose "$board" "$envfile" "$lab/full.dtb"
    [[ $(fdtget -t u "$lab/full.dtb" "$node" dead_time) == 500 ]]
    [[ $(fdtget -t u "$lab/full.dtb" "$node" bind_pwm) == $((first + 1)) ]]
    if [[ $board == h618 ]]; then
        [[ $(fdtget -t u "$lab/full.dtb" /soc/pwm3@0300a000 bind_pwm) == 2 ]]
        reject module_h616_pwm pwm2 route off
    else
        reject pwm set capture 1
        [[ $(fdtget -t u "$lab/full.dtb" "${node%?}1" bind_pwm) == 0 ]]
        reject module_a733_io add-cs 1
    fi
    upd=$(pwm set pair "$first" 1000); undo "$upd"; undo "$change"; cmp "$envfile" "$lab/original"
    if [[ $board == a733 ]]; then
        for n in 0 1 2 3 4 9 22; do pwm set capture "$n"; pwm off "$n"; done
        reject pwm set burst 2 0; reject pwm set burst 2 65537
        cap=$(pwm set capture 9)
        reject module_a733_io set i2c1 400000
        undo "$cap"
        cap=$(pwm set burst 2 65536)
        dialog_menu() { case "$1" in 'PWM and cooling') echo fan ;; *) return 1 ;; esac; }
        dialog_inputbox() { echo '0 64 128 192 255'; }
        dialog_msgbox() { echo "$2"; }
        fan=$(pwm select)
        grep -q 'opi-pwmx-a733-fan-5-0-64-128-192-255' "$envfile"
        cp "$envfile" "$lab/post-menu"
        dialog_inputbox() { return 1; }; pwm select; cmp "$envfile" "$lab/post-menu"
        unset -f dialog_menu dialog_inputbox dialog_msgbox
        reject pwm set fan 5 0 128 64 192 255
        _header_gpio_compose "$board" "$envfile" "$lab/full.dtb"
        [[ $(fdtget -t u "$lab/full.dtb" /soc@3000000/pwm0@2527012 armbian,pulse-count) == 65536 ]]
        [[ $(fdtget -t u "$lab/full.dtb" /soc@3000000/pwm-fan cooling-levels) == '0 64 128 192 255' ]]
        [[ $(fdtget -t u "$lab/full.dtb" /thermal-zones/cpul_thermal_zone/trips/trip-point@0 temperature) == 55000 ]]
        echo '# later edit' >> "$envfile"; reject undo "$fan"; sed -i '$d' "$envfile"
        undo "$fan"; undo "$cap"; cmp "$envfile" "$lab/original"
    fi
    echo "$board: PWM profiles, conflicts and rollback passed"
done
