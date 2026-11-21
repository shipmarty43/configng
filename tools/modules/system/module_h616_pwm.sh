module_options+=(
    ["module_h616_pwm,feature"]="module_h616_pwm"
    ["module_h616_pwm,desc"]="Configure the four Zero 2W header PWM channels"
    ["module_h616_pwm,example"]="select routes pwm1 pwm2 pwm3 pwm4 backups boot-rollback release-uart0 restore-uart0"
    ["module_h616_pwm,group"]="Hardware"
    ["module_h616_pwm,status"]="Preview"
)

_h616_pwm_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/h616_pwm.py" "$@"; }
_pwm_route_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/pwm_routes.py" "$@"; }

_pwm_list() (
    local dt conf="$(_ups_dfr_boot)/armbianEnv.txt"
    dt=$(mktemp) || return 1
    trap 'rm -f "$dt"' EXIT
    _zero2w_overlay_prepare compose "$conf" "$dt" pwm '' && _pwm_route_cli list "$dt"
)

_pwm_prepare() {
    local action=$1 before=$2 after=$3 folder="${2%/*}"
    if [[ $action == release || $action == restore ]]; then
        _pwm_route_cli uart0 "$before" "$after" "$(_ups_dfr_boot)" "$action"
        return
    fi
    _pwm_route_cli prepare "$before" "$folder/pwm-base.env" "$pwm_number" off &&
        _zero2w_overlay_prepare compose "$folder/pwm-base.env" "$folder/pwm-base.dtb" pwm '' &&
        _pwm_route_cli inactive "$folder/pwm-base.dtb" "$pwm_number" &&
        _pwm_route_cli prepare "$before" "$after" "$pwm_number" "$pwm_pin"
}

_pwm_channel_menu() {
    local n=$1 data action hz duty polarity pin result rc=0
    data=$(module_h616_pwm "pwm$n" status 2>&1) || { dialog_msgbox "PWM$n" "$data" 12 74; return 1; }
    action=$(dialog_menu "PWM$n" "$data" 22 78 6 -- route 'Choose header pin or remove overlay' \
        set 'Save frequency, active duty and level' start 'Start saved output' restart 'Restart with saved waveform' \
        stop 'Stop output and release channel' default 'Clear saved waveform') || return 0
    case "$action" in
        route)
            local -a pins=()
            local label
            data=$(_pwm_route_cli pins "$n") || return 1
            while IFS=$'\t' read -r pin label; do pins+=("$pin" "$label"); done <<< "$data"
            pin=$(dialog_menu "PWM$n boot route" 'One output pin per channel; applies after reboot.' 13 74 3 -- \
                "${pins[@]}" off 'Remove the header overlay') || return 0
            result=$(module_h616_pwm "pwm$n" route "$pin" 2>&1) || rc=$? ;;
        set)
            hz=$(dialog_inputbox 'PWM frequency' 'Hz (1..1000000)' '' 10 65) || return 0
            duty=$(dialog_inputbox 'PWM active duty' 'Active percent (0..100, up to two decimal places)' '' 10 70) || return 0
            polarity=$(dialog_menu 'PWM active level' "Steady-state active interval on PWM$n" 12 65 2 -- normal 'Active high' inversed 'Active low') || return 0
            result=$(module_h616_pwm "pwm$n" set "$hz" "$duty" "$polarity" 2>&1) || rc=$? ;;
        start|restart|stop|default)
            result=$(module_h616_pwm "pwm$n" "$action" 2>&1) || rc=$?
            if [[ -z $result && $rc == 0 ]]; then result=$(module_h616_pwm "pwm$n" status); fi ;;
        *) return 2 ;;
    esac
    dialog_msgbox "PWM$n" "$result" 15 78
    return "$rc"
}

module_h616_pwm() {
    local pwm_number=1 pwm_pin unit=opi-zero2w-pwm.service action label item data id result rc=0
    local -a opts=() cli=()
    if [[ ${1:-} == pwm[1-4] ]]; then
        pwm_number=${1#pwm}; shift
        if [[ $pwm_number != 1 ]]; then
            unit="opi-zero2w-pwm@$pwm_number.service"
            cli=(--channel "$pwm_number")
        fi
        if (( $# == 0 )); then _pwm_channel_menu "$pwm_number"; return; fi
    fi
    case "${1:-select}" in
        status|set|default) _h616_pwm_cli "${cli[@]}" "$@" ;;
        restart) _h616_pwm_cli "${cli[@]}" validate && systemctl restart "$unit" ;;
        start|stop) systemctl "$1" "$unit" ;;
        routes) _pwm_list ;;
        route)
            [[ $# == 2 ]] && _ups_dfr_board || return 2
            pwm_pin=$2
            _zero2w_overlay_change route pwm _pwm_prepare ;;
        release-uart0|restore-uart0)
            [[ $# == 1 ]] && _ups_dfr_board || return 2
            _zero2w_overlay_change "${1%-uart0}" pwm _pwm_prepare ;;
        backups)
            for item in "$(_ups_dfr_boot)"/armbianEnv.txt.pwm-backups/change.*; do
                [[ ! -d $item ]] || echo "${item##*/}"
            done ;;
        boot-rollback) [[ $# == 2 ]] && _ups_dfr_board || return 2
            _zero2w_overlay_change rollback pwm _pwm_prepare "$2" ;;
        select)
            data=$(_pwm_list 2>&1) || { dialog_msgbox 'Header PWM' "$data" 12 76; return 1; }
            while IFS=$'\t' read -r item label; do opts+=("$item" "$label"); done <<< "$data"
            action=$(dialog_menu 'Header PWM' 'Choose a channel or manage the boot route.' 18 78 8 -- \
                "${opts[@]}" release-uart0 'Release free UART0 pins for PWM on next boot' \
                restore-uart0 'Restore the base UART0 route' rollback 'Undo an overlay change') || return 0
            if [[ $action == pwm[1-4] ]]; then _pwm_channel_menu "${action#pwm}"; return; fi
            if [[ $action == rollback ]]; then
                opts=(); data=$(module_h616_pwm backups) || return 1
                while read -r id; do [[ -z $id ]] || opts+=("$id" 'Saved change'); done <<< "$data"
                if (( ! ${#opts[@]} )); then dialog_msgbox 'Header PWM' 'No saved route changes.' 8 65; return 0; fi
                id=$(dialog_menu 'Rollback PWM route' 'Choose the change to undo.' 16 74 8 -- "${opts[@]}") || return 0
                result=$(module_h616_pwm boot-rollback "$id" 2>&1) || rc=$?
            else
                result=$(module_h616_pwm "$action" 2>&1) || rc=$?
            fi
            dialog_msgbox 'Header PWM' "$result" 14 78
            return "$rc" ;;
        *) return 2 ;;
    esac
}
