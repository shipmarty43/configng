module_options+=(
    ["module_sx1262_mode,feature"]="module_sx1262_mode"
    ["module_sx1262_mode,desc"]="Select and verify the exclusive SX1262 owner"
    ["module_sx1262_mode,example"]="select status profile check-meshtastic set apply"
    ["module_sx1262_mode,group"]="Hardware"
    ["module_sx1262_mode,status"]="Preview"
)

_sx1262_mode_cli() {
    python3 "${script_dir:-/usr/bin}/../share/armbian-config/sx1262_mode.py" "$@"
}

function module_sx1262_mode() {
    local profile prompt choice output result=0
    case "${1:-select}" in
        profile|status|set|apply|check-meshtastic) _sx1262_mode_cli "$@"; return ;;
        select) ;;
        *) return 2 ;;
    esac
    profile=$(_sx1262_mode_cli profile) || return 1
    if [[ "$profile" == no-radio ]]; then
        prompt='No-radio profile. Select the test owner of the simulated SX1262 lock.'
    else
        prompt='Hardware profile. Selecting a radio backend can start RF transmission.'
    fi
    choice=$(dialog_menu 'SX1262 mode' "$prompt" 18 76 6 -- \
        status 'Current owner and saved mode' off 'Off' meshtastic 'Meshtastic' \
        reticulum 'Reticulum' lorawan 'LoRaWAN' check-meshtastic 'Check Meshtastic hardware profile (read only)') || return 0
    case "$choice" in
        status|check-meshtastic) output=$(_sx1262_mode_cli "$choice" 2>&1) || result=$? ;;
        off|meshtastic|reticulum|lorawan)
            output=$(_sx1262_mode_cli set "$choice" 2>&1) || result=$? ;;
        *) return 0 ;;
    esac
    dialog_msgbox 'SX1262 mode' "$output" 16 76
    return "$result"
}
