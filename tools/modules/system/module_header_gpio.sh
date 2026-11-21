module_options+=(
    ["module_header_gpio,feature"]="module_header_gpio"
    ["module_header_gpio,desc"]="Orange Pi header GPIO electrical settings"
    ["module_header_gpio,group"]="Hardware"
    ["module_header_gpio,status"]="Preview"
)

_header_gpio_board() {
    [[ -r "$(_ups_dfr_dt)/compatible" ]] || return 1
    if _ups_dfr_board && grep -zFxq 'allwinner,sun50i-h618' "$(_ups_dfr_dt)/compatible"; then
        echo h618
    elif _a733_board; then
        echo a733
    else
        return 1
    fi
}
_header_gpio_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/header_gpio.py" "$@"; }
_header_gpio_live() {
    local board
    board=$(_header_gpio_board) && python3 "${script_dir:-/usr/bin}/../share/armbian-config/header_gpio_live.py" "$board" "$@"
}
_header_gpio_driver() { modinfo -k "$(uname -r)" -F name opi_header_gpio 2>/dev/null | grep -Fxq opi_header_gpio; }

_header_gpio_compose() {
    if [[ $1 == h618 ]]; then
        _zero2w_overlay_prepare compose "$2" "$3" gpio ''
    else
        _a733_io_cli "$2" compose-dtb "$3"
    fi
}

_header_gpio_process() (
    local op=$1 env=$2 board dir folder
    shift 2
    board=$(_header_gpio_board) || return 1
    folder="$(_ups_dfr_boot)/overlay-user"
    dir=$(mktemp -d) || return 1
    trap 'rm -rf "$dir"' EXIT
    _header_gpio_cli strip "$board" "$env" "$folder" "$dir/base.env" &&
        _header_gpio_compose "$board" "$dir/base.env" "$dir/base.dtb" || return 1
    if [[ $op == verify ]]; then
        _header_gpio_compose "$board" "$env" "$dir/full.dtb" || return 1
        _header_gpio_cli verify "$board" "$env" "$folder" "$dir/base.dtb" "$dir/full.dtb"
    else
        _header_gpio_cli "$op" "$board" "$env" "$folder" "$dir/base.dtb" "$@"
    fi
)
_header_gpio_prepare() { _header_gpio_process "$1" "$2" "$3" "${gpio_args[@]}"; }
_header_gpio_verify() { _header_gpio_process verify "$1"; }

_header_gpio_precommit() {
    local needs
    needs=$(_header_gpio_cli driver-needed "$(_header_gpio_board)" "$1" "$(_ups_dfr_boot)/overlay-user" "$2") || return 1
    if [[ $needs == yes ]] && ! _header_gpio_driver; then
        echo 'Install the header GPIO helper for the boot kernel (see GPIO01 driver).' >&2
        return 1
    fi
    _header_gpio_live check "$1" "$2" "$(_ups_dfr_boot)/overlay-user"
}

_header_gpio_menu() {
    local rows pin desc action bias drive usec data id current rc=0
    local -a opts=() args=()
    rows=$(module_header_gpio list 2>&1) || { dialog_msgbox 'GPIO header' "$rows" 12 78; return 1; }
    while IFS=$'\t' read -r pin desc; do opts+=("$pin" "$desc"); done <<< "$rows"
    if _ups_dfr_board; then opts+=(wiringpi 'WiringPi header report'); fi
    pin=$(dialog_menu 'GPIO header' 'Physical 40-pin header. Settings below are for the next boot.' 22 88 14 -- \
        live 'Live gpiochip consumers' rollback 'Restore a saved boot configuration' driver 'Electrical preset driver' "${opts[@]}") || return 0
    case "$pin" in
        live)
            local report
            report=$(mktemp) || return 1
            module_header_gpio status > "$report" 2>&1 || rc=$?
            case ${DIALOG:-dialog} in
                dialog) dialog --title 'Live GPIO line information' --textbox "$report" 22 86 || : ;;
                whiptail) whiptail --title 'Live GPIO line information' --scrolltext --textbox "$report" 22 86 || : ;;
                *) cat "$report" ;;
            esac
            rm -f -- "$report"
            return "$rc" ;;
        wiringpi) module_zero2w_gpio select; return ;;
        driver)
            if _header_gpio_driver; then data='Installed for the running kernel.'
            else
                dialog_yesno 'GPIO preset driver' 'Build the one-shot bias and drive helper with DKMS for the running kernel?' 'Build' 'Cancel' 10 74 || return 0
                data=$(module_header_gpio install-driver 2>&1) || rc=$?
            fi
            dialog_msgbox 'GPIO preset driver' "$data" 15 78; return "$rc" ;;
        rollback)
            opts=()
            while read -r id; do [[ -z $id ]] || opts+=("$id" 'Undo saved GPIO change'); done < <(module_header_gpio backups)
            if (( ! ${#opts[@]} )); then dialog_msgbox 'GPIO rollback' 'No saved changes.' 9 64; return; fi
            id=$(dialog_menu 'GPIO rollback' 'Choose a saved change.' 15 70 7 -- "${opts[@]}") || return 0
            args=(rollback "$id") ;;
        *)
            desc=$(module_header_gpio info "$pin") || return 1
            action=$(dialog_menu "GPIO pin $pin" "$desc" 13 82 2 -- set 'Edit next-boot settings' default 'Restore board defaults for this pin') || return 0
            args=("$action" "$pin")
            if [[ $action == set ]]; then
                current=$(module_header_gpio get "$pin") || return 1
                read -r bias drive usec <<< "$current"
                bias=$(dialog_menu 'Internal bias' 'Choose the pull resistor.' 14 76 4 --default-item "$bias" -- default 'Board default' off 'Disable pull' up 'Pull up' down 'Pull down') || return 0
                drive=$(dialog_menu 'Drive strength' 'Nominal output drive (mA).' 14 76 5 --default-item "$drive" -- default 'Board default' 10 '10 mA' 20 '20 mA' 30 '30 mA' 40 '40 mA') || return 0
                usec=$(dialog_inputbox 'IRQ bank debounce' 'Requested microseconds for the entire bank (1..3906), or default.' "$usec" 11 80) || return 0
                args+=("$bias" "$drive" "$usec")
            fi ;;
    esac
    data=$(module_header_gpio "${args[@]}" 2>&1) || rc=$?
    dialog_msgbox 'GPIO header' "$data" 20 82
    return "$rc"
}

module_header_gpio() {
    local op=${1:-select} root backup
    local -a gpio_args=("${@:2}")
    _header_gpio_board >/dev/null || { echo 'Expected Orange Pi Zero 2W or Zero 3W.' >&2; return 1; }
    root=$(_ups_dfr_boot)
    case "$op" in
        select) _header_gpio_menu ;;
        list|info|get) _header_gpio_process "$op" "$root/armbianEnv.txt" "${gpio_args[@]}" ;;
        status) _header_gpio_live status ;;
        verify) _header_gpio_verify "$root/armbianEnv.txt" ;;
        install-driver)
            _header_gpio_driver && { echo 'Already installed.'; return; }
            command -v dkms >/dev/null && [[ -d /lib/modules/$(uname -r)/build ]] || { echo 'Install DKMS and matching kernel headers first.' >&2; return 1; }
            dkms install -j 1 -m opi-header-gpio -v 1.0 -k "$(uname -r)" && _header_gpio_driver ;;
        backups)
            for backup in "$root"/armbianEnv.txt.header-gpio-backups/change.*; do [[ ! -d $backup ]] || echo "${backup##*/}"; done ;;
        set|default|rollback)
            [[ -f $root/boot.scr && ! -e $root/extlinux/extlinux.conf ]] &&
                grep -aFq 'armbianEnv.txt' "$root/boot.scr" && grep -aFq 'overlay-user/${overlay_file}.dtbo' "$root/boot.scr" || { echo 'Unsupported overlay boot route.' >&2; return 1; }
            case "$op" in
                set) [[ $# == 5 ]] || return 2 ;;
                *) [[ $# == 2 ]] || return 2 ;;
            esac
            _zero2w_overlay_change "$op" header-gpio _header_gpio_prepare "${2:-}" ;;
        *) return 2 ;;
    esac
}
