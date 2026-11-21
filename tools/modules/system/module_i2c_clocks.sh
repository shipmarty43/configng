module_options+=(
    ["module_i2c_clocks,feature"]="module_i2c_clocks"
    ["module_i2c_clocks,desc"]="H616 I2C controller clocks and attached DT clients"
    ["module_i2c_clocks,example"]="select list status grid set default default-all backups rollback"
    ["module_i2c_clocks,group"]="Hardware"
    ["module_i2c_clocks,status"]="Preview"
)

_i2c_clocks_prepare() { _bus_clocks_prepare i2c_clocks "$@" "${i2c_args[@]}"; }

module_i2c_clocks() {
    local action=${1:-select} item desc data bus request hz result rc=0 folder
    local -a i2c_args=("${@:2}") options=()
    case "$action" in
        list|status|grid) _bus_clocks_read i2c_clocks "$@" ;;
        set|default|default-all|rollback)
            _ups_dfr_board || return 1
            [[ $action != default-all || $# == 1 ]] && [[ $action != rollback || $# == 2 ]] || return 2
            _zero2w_overlay_change "$action" i2c-clocks _i2c_clocks_prepare "${2:-}" ;;
        backups)
            for folder in "$(_ups_dfr_boot)"/armbianEnv.txt.i2c-clocks-backups/change.*; do
                [[ ! -d $folder ]] || echo "${folder##*/}"
            done ;;
        select)
            data=$(module_i2c_clocks list 2>&1) || { dialog_msgbox 'I2C clocks' "$data" 11 75; return 1; }
            while IFS=$'\t' read -r item desc; do options+=("$item" "$desc"); done <<< "$data"
            bus=$(dialog_menu 'I2C clocks' 'Select a physical bus. A clock change applies to all its clients after reboot.' 20 78 9 -- \
                "${options[@]}" rollback 'Restore a saved boot configuration' default-all 'Clear all I2C clock overrides') || return 0
            if [[ $bus == rollback ]]; then
                data=$(module_i2c_clocks backups)
                options=()
                while read -r item; do [[ ! $item ]] || options+=("$item" 'Restore saved selection'); done <<< "$data"
                if (( ! ${#options[@]} )); then dialog_msgbox 'I2C clocks' 'No clock backups.' 8 60; return 0; fi
                item=$(dialog_menu 'I2C rollback' 'Choose the change to restore.' 16 75 8 -- "${options[@]}") || return 0
                result=$(module_i2c_clocks rollback "$item" 2>&1) || rc=$?
            elif [[ $bus == default-all ]]; then
                dialog_yesno 'I2C clocks' 'Restore board defaults on all buses?' 'Restore' 'Cancel' 9 65 || return 0
                result=$(module_i2c_clocks default-all 2>&1) || rc=$?
            else
                data=$(module_i2c_clocks status "$bus" 2>&1) || { dialog_msgbox 'I2C clocks' "$data" 10 75; return 1; }
                request=$(dialog_menu "$bus SCL" "$data" 19 78 5 -- 100000 'Standard-mode (100 kHz)' 400000 'Fast-mode (400 kHz)' \
                    grid 'Select a divider frequency' custom 'Enter request in Hz' default 'Restore board default') || return 0
                case "$request" in
                    grid)
                        data=$(module_i2c_clocks grid "$bus") || return 1
                        options=()
                        while IFS=$'\t' read -r hz desc; do [[ $hz =~ ^[0-9]+$ ]] && options+=("$hz" "$desc"); done <<< "$data"
                        request=$(dialog_menu 'Calculated SCL in Hz' "${data%%$'\n'*}" 20 76 10 -- "${options[@]}") || return 0 ;;
                    custom) request=$(dialog_inputbox 'I2C clock' 'Requested Hz for the next boot' '' 10 68) || return 0 ;;
                esac
                if [[ $request == default ]]; then
                    result=$(module_i2c_clocks default "$bus" 2>&1) || rc=$?
                else
                    result=$(module_i2c_clocks set "$bus" "$request" 2>&1) || rc=$?
                fi
            fi
            dialog_msgbox 'I2C clocks' "$result" 15 76
            return "$rc" ;;
        *) return 2 ;;
    esac
}
