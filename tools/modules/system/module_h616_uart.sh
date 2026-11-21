module_options+=(
    ["module_h616_uart,feature"]="module_h616_uart"
    ["module_h616_uart,desc"]="Configure an idle Zero 2W UART"
    ["module_h616_uart,example"]="select list rates status set rollback"
    ["module_h616_uart,group"]="Hardware"
    ["module_h616_uart,status"]="Preview"
)

_h616_uart_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/h616_uart.py" "$@"; }
module_h616_uart() {
    local tty label data action baud bits parity stops result rc=0
    local -a options=()
    case "${1:-select}" in
        list|rates|status|set|rollback) _h616_uart_cli "$@"; return ;;
        select) ;;
        *) return 2 ;;
    esac
    data=$(_h616_uart_cli list 2>&1) || { dialog_msgbox 'UART' "$data" 10 72; return 1; }
    while IFS=$'\t' read -r tty label; do [[ -z $tty ]] || options+=("$tty" "$label"); done <<< "$data"
    if (( ! ${#options[@]} )); then dialog_msgbox 'UART' 'No enabled H616 UART with a Linux tty.' 9 72; return 0; fi
    tty=$(dialog_menu 'UART ports' 'Select a physical UART.' 17 76 8 -- "${options[@]}") || return 0
    data=$(_h616_uart_cli status "$tty" 2>&1) || { dialog_msgbox 'UART' "$data" 10 72; return 1; }
    action=$(dialog_menu "$tty" "$data" 13 76 3 -- set 'Set runtime baud and framing' rollback 'Restore previous settings') || return 0
    if [[ $action == rollback ]]; then
        result=$(_h616_uart_cli rollback "$tty" 2>&1) || rc=$?
    else
        data=$(_h616_uart_cli rates) || return 1
        options=()
        while read -r baud; do options+=("$baud" 'baud'); done <<< "$data"
        baud=$(dialog_menu "$tty baud" 'Requested baud rate' 19 64 10 --default-item 115200 -- "${options[@]}") || return 0
        bits=$(dialog_menu 'Data bits' 'Character length' 13 60 4 -- 8 '8 bits' 7 '7 bits' 6 '6 bits' 5 '5 bits') || return 0
        parity=$(dialog_menu 'Parity' 'Parity checking' 12 60 3 -- none None even Even odd Odd) || return 0
        local long=2
        [[ $bits != 5 ]] || long=1.5
        stops=$(dialog_menu 'Stop bits' 'Stop length' 11 60 2 -- 1 '1 stop bit' "$long" "$long stop bits") || return 0
        result=$(_h616_uart_cli set "$tty" "$baud" "$bits" "$parity" "$stops" 2>&1) || rc=$?
    fi
    dialog_msgbox 'UART runtime settings' "$result" 12 74
    return "$rc"
}
