module_options+=(
    ["module_pwm_modes,feature"]="module_pwm_modes"
    ["module_pwm_modes,desc"]="Header PWM capture, bursts, complementary pairs and thermal fan levels"
    ["module_pwm_modes,group"]="Hardware"
    ["module_pwm_modes,status"]="Preview"
)

_pwm_modes_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/pwm_modes.py" "$@"; }
_pwm_modes_live() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/pwm_modes_live.py" "$@"; }
_pwm_modes_verify() (
    local board tmp env=$1 folder="$(_ups_dfr_boot)/overlay-user"
    board=$(_header_gpio_board) && tmp=$(mktemp -d) || return 1
    trap 'rm -rf "$tmp"' EXIT
    _pwm_modes_cli strip "$board" "$env" "$folder" "$tmp/base.env" &&
        _header_gpio_compose "$board" "$tmp/base.env" "$tmp/base.dtb" &&
        _header_gpio_compose "$board" "$env" "$tmp/full.dtb" &&
        _pwm_modes_cli verify "$board" "$env" "$folder" "$tmp/base.dtb" "$tmp/full.dtb"
)
_pwm_modes_prepare() {
    _pwm_modes_cli prepare "$board" "$2" "$(_ups_dfr_boot)/overlay-user" "$3" "${params[@]}"
}

_pwm_modes_menu() {
    local board=$1 action n item data mode period duty amount extra id rc=0
    local driver_note='Live signal tests require the PWM002 kernel patch.'
    if [[ $board == a733 ]]; then driver_note+=' The fan curve works with the stock driver.'; fi
    local -a actions=(pair 'Save complementary pair and dead time' run 'Test a booted profile'
                      off 'Remove a saved profile' rollback 'Undo a boot change')
    local -a args=() opts=()
    if [[ $board == a733 ]]; then
        actions+=(capture 'Route a capture input' burst 'Save a hardware pulse count'
                  fan 'Edit five thermal fan levels' fan-status 'Read live fan duty and cooling levels')
    fi
    data=$(module_pwm_modes list 2>&1) || { dialog_msgbox 'PWM profiles' "$data" 12 78; return 1; }
    action=$(dialog_menu 'PWM and cooling' "$driver_note Saved for next boot: ${data:-board defaults}" 22 88 9 -- "${actions[@]}") || return 0
    case "$action" in
        fan)
            local curve='0 50 102 170 255'
            while read -r item; do
                if [[ $item == opi-pwmx-a733-fan-5-* ]]; then
                    curve=${item#opi-pwmx-a733-fan-5-}; curve=${curve//-/ }
                fi
            done <<< "$data"
            amount=$(dialog_inputbox 'Thermal fan' 'Five increasing duty levels (0..255). Keep the endpoints 0 and 255.' "$curve" 12 80) || return 0
            read -r -a opts <<< "$amount"; args=(set fan 5 "${opts[@]}") ;;
        fan-status) args=(fan-status) ;;
        rollback)
            while read -r id; do [[ -z $id ]] || opts+=("$id" 'Restore previous selection'); done < <(module_pwm_modes backups)
            if (( ! ${#opts[@]} )); then dialog_msgbox 'PWM profiles' 'No saved changes.' 8 60; return; fi
            id=$(dialog_menu 'PWM rollback' 'Select the change to undo.' 16 72 8 -- "${opts[@]}") || return 0
            args=(rollback "$id") ;;
        run|off)
            while read -r item; do
                [[ -n $item ]] || continue
                IFS=- read -r _ _ _ mode n extra <<< "$item"
                if [[ $action == off || $mode != fan ]]; then opts+=("$item" "$mode, channel $n"); fi
            done <<< "$data"
            if (( ! ${#opts[@]} )); then dialog_msgbox 'PWM profiles' 'No saved profile for this action.' 8 68; return; fi
            item=$(dialog_menu 'PWM profile' 'A live test requires the matching profile after boot.' 17 85 8 -- "${opts[@]}") || return 0
            IFS=- read -r _ _ _ mode n extra <<< "$item"
            if [[ $action == off ]]; then args=(off "$n")
            else
                args=(run "$mode" "$n")
                if [[ $mode != capture ]]; then
                    period=$(dialog_inputbox 'PWM period' 'Period in ns (1000..2730666)' '100000' 10 66) || return 0
                    duty=$(dialog_inputbox 'PWM high time' 'Active interval in ns' '50000' 10 64) || return 0
                    args+=("$period" "$duty")
                    if [[ $mode == pair ]]; then
                        amount=$(dialog_inputbox 'Pair test' 'Run duration in ms (1..60000)' '100' 10 64) || return 0
                        args+=("$amount")
                    fi
                fi
            fi ;;
        pair|capture|burst)
            if [[ $action == pair && $board == h618 ]]; then opts=(2 'PWM2 + PWM3 (select both routes in PWM001)')
            elif [[ $action == pair ]]; then opts=(0 'PWM0-0/1, pins 7/32' 2 'PWM0-2/3, pins 36/33' 8 'PWM0-8/9, pins 35/40 (check PB6 IRQ)')
            else opts=(0 'PB4 pin 7' 1 'PD1 pin 32' 2 'PD2 pin 36' 3 'PD3 pin 33' 4 'PD4 pin 37' 8 'PB6 pin 35' 9 'PB7 pin 40' 22 'Standby PL4 pin 28'); fi
            n=$(dialog_menu 'Header channel' 'Pin and PWM consumers are checked before saving.' 17 84 9 -- "${opts[@]}") || return 0
            args=(set "$action" "$n")
            if [[ $action == pair ]]; then
                amount=$(dialog_inputbox 'Pair dead time' 'Nanoseconds (42..10666), rounded down to 24 MHz ticks' '500' 10 78) || return 0
                args+=("$amount")
            elif [[ $action == burst ]]; then
                amount=$(dialog_inputbox 'Burst length' 'Hardware period count, 1..65536' '10' 10 66) || return 0
                args+=("$amount")
            fi ;;
        *) return 2 ;;
    esac
    data=$(module_pwm_modes "${args[@]}" 2>&1) || rc=$?
    dialog_msgbox 'PWM and cooling' "$data" 16 85
    return "$rc"
}

module_pwm_modes() {
    local board action=${1:-select} boot id
    local -a params=()
    board=$(_header_gpio_board) || return 1
    boot=$(_ups_dfr_boot)
    if [[ $board == a733 && $action =~ ^(set|off|rollback)$ ]]; then
        [[ -f $boot/boot.scr && ! -e $boot/extlinux/extlinux.conf ]] &&
            grep -aFq 'armbianEnv.txt' "$boot/boot.scr" &&
            grep -aFq 'overlay-user/${overlay_file}.dtbo' "$boot/boot.scr" || {
                echo 'Unrecognized Armbian overlay boot route.' >&2; return 1;
            }
    fi
    if (( $# )); then shift; fi
    case "$action" in
        list) _pwm_modes_cli list "$board" "$boot/armbianEnv.txt" "$boot/overlay-user" ;;
        verify) _pwm_modes_verify "$boot/armbianEnv.txt" ;;
        set) [[ $# -ge 2 ]] || return 2
            params=("$@"); _zero2w_overlay_change set pwm-modes _pwm_modes_prepare ;;
        off) [[ $# == 1 ]] || return 2
            params=(off "$1"); _zero2w_overlay_change set pwm-modes _pwm_modes_prepare ;;
        run) [[ $# -ge 2 && $1 =~ ^(pair|capture|burst)$ ]] || return 2
            _pwm_modes_live "$board" "$@" ;;
        fan-status) _pwm_modes_live "$board" fan ;;
        backups) for id in "$boot"/armbianEnv.txt.pwm-modes-backups/change.*; do
            [[ ! -d $id ]] || echo "${id##*/}"; done ;;
        rollback) [[ $# == 1 ]] || return 2
            _zero2w_overlay_change rollback pwm-modes _pwm_modes_prepare "$1" ;;
        select) _pwm_modes_menu "$board" ;;
        *) return 2 ;;
    esac
}
