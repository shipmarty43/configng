module_options+=(
    ["module_header_bus,feature"]="module_header_bus"
    ["module_header_bus,desc"]="I2C adapter recovery and RS-485 direction control"
    ["module_header_bus,group"]="Hardware"
    ["module_header_bus,status"]="Preview"
)

module_header_bus() {
    local bus name action data rc=0
    local -a entries=() actions=()
    _header_gpio_board >/dev/null || return 1
    if [[ ${1:-select} != select ]]; then
        if [[ $1 == i2c && $2 != list && ! -c /dev/opi-i2c-recovery ]]; then
            modprobe opi_i2c_recovery 2>/dev/null || :
        fi
        python3 "${script_dir:-/usr/bin}/../share/armbian-config/header_bus_diag.py" "$@"
        return
    fi
    bus=$(dialog_menu 'Header bus diagnostics' 'Choose a live controller interface.' 12 72 2 -- i2c 'Registered devices and bus recovery' rs485 'Serial RS-485 capability and mode') || return 0
    data=$(module_header_bus "$bus" list 2>&1) || { dialog_msgbox 'Header buses' "$data" 10 78; return 1; }
    while read -r name; do [[ -z $name ]] || entries+=("$name" 'Live header controller'); done <<< "$data"
    if (( ! ${#entries[@]} )); then dialog_msgbox 'Header buses' 'No matching controller on the running device tree.' 10 78; return; fi
    name=$(dialog_menu 'Controller' 'Choose a port.' 16 72 8 -- "${entries[@]}") || return 0
    data=$(module_header_bus "$bus" status "$name" 2>&1) || { dialog_msgbox "$name" "$data" 11 78; return 1; }
    if [[ $bus == i2c ]]; then
        if [[ $data != *'adapter recovery supported' ]]; then dialog_msgbox "$name" "$data" 12 80; return; fi
        actions=(recover 'Request recovery under the kernel adapter lock')
    else
        actions=(high 'Enable, RTS high during TX' low 'Enable, RTS low during TX' off 'Disable RS-485')
    fi
    action=$(dialog_menu "$name" "$data" 16 82 4 -- "${actions[@]}") || return 0
    data=$(module_header_bus "$bus" "$action" "$name" 2>&1) || rc=$?
    dialog_msgbox "$name" "$data" 12 80
    return "$rc"
}
