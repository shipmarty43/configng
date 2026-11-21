module_options+=(
    ["module_h616_uart,feature"]="module_h616_uart"
    ["module_h616_uart,desc"]="Configure an idle Zero 2W UART"
    ["module_h616_uart,example"]="select list rates status set rollback routes enable enable-rtscts enable-rtscts-ph disable backups boot-rollback save saved forget restore-profile"
    ["module_h616_uart,group"]="Hardware"
    ["module_h616_uart,status"]="Preview"
)

_h616_uart_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/h616_uart.py" "$@"; }
_uart_get_framing() {
    local label=$1 baud bits parity stops data long=2
    local -a options=()
    data=$(_h616_uart_cli rates) || return 1
    while read -r baud; do options+=("$baud" 'baud'); done <<< "$data"
    baud=$(dialog_menu "$label baud" 'Requested baud rate' 19 64 10 --default-item 115200 -- "${options[@]}") || return 1
    bits=$(dialog_menu 'Data bits' 'Character length' 13 60 4 -- 8 '8 bits' 7 '7 bits' 6 '6 bits' 5 '5 bits') || return 1
    parity=$(dialog_menu 'Parity' 'Parity checking' 12 60 3 -- none None even Even odd Odd) || return 1
    [[ $bits != 5 ]] || long=1.5
    stops=$(dialog_menu 'Stop bits' 'Stop length' 11 60 2 -- 1 '1 stop bit' "$long" "$long stop bits") || return 1
    printf '%s %s %s %s\n' "$baud" "$bits" "$parity" "$stops"
}

module_h616_uart() {
    local tty label data action result rc=0 uart_port=${2:-} folder
    local -a options=() params=()
    case "${1:-select}" in
        list|rates|status|set|rollback|save|saved|forget|restore-profile) _h616_uart_cli "$@"; return ;;
        routes) _uart_routes_list; return ;;
        enable|enable-rtscts|enable-rtscts-ph|disable)
            [[ $# == 2 ]] && _ups_dfr_board || return 2
            _zero2w_overlay_change "$1" uart _uart_prepare; return ;;
        backups)
            for folder in "$(_ups_dfr_boot)"/armbianEnv.txt.uart-backups/change.*; do
                [[ ! -d $folder ]] || echo "${folder##*/}"
            done
            return ;;
        boot-rollback) [[ $# == 2 ]] && _ups_dfr_board || return 2
            _zero2w_overlay_change rollback uart _uart_prepare "$2"; return ;;
        select) ;;
        *) return 2 ;;
    esac
    data=$(_h616_uart_cli list 2>&1) || { dialog_msgbox 'UART' "$data" 10 72; return 1; }
    options=(boot 'Header overlays and saved boot settings')
    while IFS=$'\t' read -r tty label; do [[ -z $tty ]] || options+=("$tty" "$label"); done <<< "$data"
    tty=$(dialog_menu 'UART ports' 'Choose boot configuration or a live port.' 17 76 8 -- "${options[@]}") || return 0
    if [[ $tty == boot ]]; then _uart_boot_menu; return; fi
    data=$(_h616_uart_cli status "$tty" 2>&1) || { dialog_msgbox 'UART' "$data" 10 72; return 1; }
    action=$(dialog_menu "$tty" "$data" 13 76 3 -- set 'Set runtime baud and framing' rollback 'Restore previous settings') || return 0
    if [[ $action == rollback ]]; then
        result=$(_h616_uart_cli rollback "$tty" 2>&1) || rc=$?
    else
        data=$(_uart_get_framing "$tty") || return 0
        read -r -a params <<< "$data"
        result=$(_h616_uart_cli set "$tty" "${params[@]}" 2>&1) || rc=$?
    fi
    dialog_msgbox 'UART runtime settings' "$result" 12 74
    return "$rc"
}

_uart_boot_menu() {
    local data port desc action result rc=0 id
    local -a options=() params=()
    data=$(_uart_routes_list 2>&1) || { dialog_msgbox 'UART boot configuration' "$data" 12 76; return 1; }
    while IFS=$'\t' read -r port desc; do options+=("$port" "$desc"); done <<< "$data"
    port=$(dialog_menu 'UART boot configuration' 'Physical TX/RX header pins and next-boot routes' 17 78 7 -- \
        "${options[@]}" rollback 'Restore previous boot overlay selection') || return 0
    if [[ $port == rollback ]]; then
        options=()
        data=$(module_h616_uart backups) || return 1
        while read -r id; do [[ -z $id ]] || options+=("$id" 'Saved overlay change'); done <<< "$data"
        if (( ! ${#options[@]} )); then dialog_msgbox 'UART overlays' 'No saved changes.' 8 68; return 0; fi
        id=$(dialog_menu 'Rollback UART overlay' 'Choose the change to undo.' 16 76 8 -- "${options[@]}") || return 0
        result=$(module_h616_uart boot-rollback "$id" 2>&1) || rc=$?
    else
        data=$(_h616_uart_cli saved "$port" 2>&1) || { dialog_msgbox 'UART profile' "$data" 10 72; return 1; }
        options=()
        if [[ $port != uart0 ]]; then options+=(enable 'Enable header TX/RX on next boot' disable 'Remove header overlay on next boot'); fi
        case "$port" in
            uart2) options+=(enable-rtscts 'TX/RX/RTS/CTS on 15/22/5/3 (PI)' enable-rtscts-ph 'TX/RX/RTS/CTS on 24/23/19/21 (PH)') ;;
            uart3) options+=(enable-rtscts 'TX/RX/RTS/CTS on 28/27/32/33') ;;
            uart4) options+=(enable-rtscts 'TX/RX/RTS/CTS on 7/16/31/37') ;;
        esac
        action=$(dialog_menu "$port boot settings" "$data" 18 78 7 -- "${options[@]}" \
            save 'Save baud and framing for future boots' forget 'Clear saved profile') || return 0
        if [[ $action == save ]]; then
            data=$(_uart_get_framing "$port") || return 0
            read -r -a params <<< "$data"
        fi
        result=$(module_h616_uart "$action" "$port" "${params[@]}" 2>&1) || rc=$?
    fi
    dialog_msgbox 'UART boot configuration' "$result" 13 76
    return "$rc"
}

_uart_route_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/uart_routes.py" "$@"; }

_uart_overlay_validate() (
    local env=$1 dt
    dt=$(mktemp) || return 1
    trap 'rm -f "$dt"' EXIT
    _zero2w_overlay_prepare compose "$env" "$dt" uart '' && _uart_route_cli verify "$dt" "$env" "$(_ups_dfr_boot)/overlay-user"
)

_uart_routes_list() (
    local env dt
    env="$(_ups_dfr_boot)/armbianEnv.txt"
    dt=$(mktemp) || return 1
    trap 'rm -f "$dt"' EXIT
    _zero2w_overlay_prepare compose "$env" "$dt" uart '' && _uart_route_cli list "$dt" "$env"
)

_uart_prepare() {
    local action=$1 before=$2 after=$3 dir="${2%/*}" folder="$(_ups_dfr_boot)/overlay-user"
    # Strip this provider first, to detect another route to the same UART.
    _uart_route_cli prepare "$before" "$dir/uart-base.env" "$folder" "$uart_port" disable &&
        _zero2w_overlay_prepare compose "$dir/uart-base.env" "$dir/uart-base.dtb" uart '' &&
        _uart_route_cli inactive "$dir/uart-base.dtb" "$uart_port" &&
        _uart_route_cli prepare "$before" "$after" "$folder" "$uart_port" "$action"
}
