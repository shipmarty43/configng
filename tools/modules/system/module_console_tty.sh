module_options+=(
    ["module_console_tty,feature"]="module_console_tty"
    ["module_console_tty,desc"]="Choose the Linux console TTY on Orange Pi Zero 2W"
    ["module_console_tty,example"]="select list status set backups rollback help"
    ["module_console_tty,group"]="Hardware"
    ["module_console_tty,status"]="Preview"
    ["module_console_tty,author"]="@shipmarty43"
    ["module_console_tty,maintainer"]="@shipmarty43"
)
function _console_tty_available() {
    [[ -r "${script_dir:-/usr/bin}/../share/armbian-config/console_tty.py" ]] &&
        grep -zFxq 'xunlong,orangepi-zero2w' /sys/firmware/devicetree/base/compatible 2>/dev/null
}
function _console_tty_cli() {
    python3 "${script_dir:-/usr/bin}/../share/armbian-config/console_tty.py" "$@"
}
function module_console_tty() {
    local choice data item label output rc=0
    local -a options=()
    case "${1:-select}" in
        list|status|set|backups|rollback) _console_tty_cli "$@" ;;
        select)
            data=$(_console_tty_cli list) || return 1
            while IFS=$'\t' read -r item label; do
                [[ -z "$item" ]] || options+=("$item" "$label")
            done <<< "$data"
            choice=$(dialog_menu 'Linux console TTY' 'Choose the console for the next boot.' 21 78 10 -- \
                status 'Active and next boot consoles' "${options[@]}" rollback 'Restore saved console settings') || return 0
            case "$choice" in
                status) output=$(_console_tty_cli status 2>&1) || rc=$? ;;
                rollback)
                    data=$(_console_tty_cli backups) || return 1
                    if [[ -z "$data" ]]; then dialog_msgbox 'Linux console TTY' 'No saved changes.' 9 60; return; fi
                    options=()
                    while read -r item; do options+=("$item" 'Saved console settings'); done <<< "$data"
                    item=$(dialog_menu 'Restore console' 'Select the change to undo' 16 72 6 -- "${options[@]}") || return 0
                    output=$(_console_tty_cli rollback "$item" 2>&1) || rc=$? ;;
                *) output=$(_console_tty_cli set "$choice" 2>&1) || rc=$? ;;
            esac
            dialog_msgbox 'Linux console TTY' "$output" 15 78
            return "$rc" ;;
        help) echo 'module_console_tty select|status|list|set TARGET|backups|rollback change.ID' ;;
        *) return 1 ;;
    esac
}
