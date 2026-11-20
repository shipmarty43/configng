module_options+=(
    ["module_sx1262_mode,feature"]="module_sx1262_mode"
    ["module_sx1262_mode,desc"]="Select and verify the exclusive SX1262 owner"
    ["module_sx1262_mode,example"]="select status diagnostics profile check-meshtastic check-reticulum spi spi-grid set apply"
    ["module_sx1262_mode,group"]="Hardware"
    ["module_sx1262_mode,status"]="Preview"
)

_sx1262_mode_cli() {
    python3 "${script_dir:-/usr/bin}/../share/armbian-config/sx1262_mode.py" "$@"
}

function module_sx1262_mode() {
    local profile prompt choice output result=0
    case "${1:-select}" in
        profile|status|diagnostics|set|apply|check-meshtastic|check-reticulum|spi|spi-grid) _sx1262_mode_cli "$@"; return ;;
        select) ;;
        *) return 2 ;;
    esac
    profile=$(_sx1262_mode_cli profile) || return 1
    if [[ "$profile" == no-radio ]]; then
        prompt='No-radio profile. Select the test owner of the simulated SX1262 lock.'
    else
        prompt='Hardware profile. Selecting a radio backend can start RF transmission.'
    fi
    choice=$(dialog_menu 'SX1262 mode' "$prompt" 21 78 9 -- \
        status 'Current owner and saved mode' off 'Off' meshtastic 'Meshtastic' \
        reticulum 'Reticulum' lorawan 'LoRaWAN' check-meshtastic 'Check Meshtastic hardware profile (read only)' \
        check-reticulum 'Check Reticulum hardware profile (read only)' spi 'SPI bus clock (Hz)' diagnostics 'Diagnostics: ownership, bus and RNode RX') || return 0
    case "$choice" in
        diagnostics)
            while :; do
                output=$(_sx1262_mode_cli diagnostics 2>&1) || { dialog_msgbox 'SX1262 diagnostics' "$output" 12 76; return 1; }
                dialog_yesno 'SX1262 diagnostics' "$output" 'Refresh' 'Back' 21 78 || return 0
            done ;;
        spi) _sx1262_clock_menu; return ;;
        status|check-meshtastic|check-reticulum) output=$(_sx1262_mode_cli "$choice" 2>&1) || result=$? ;;
        off|meshtastic|reticulum|lorawan)
            output=$(_sx1262_mode_cli set "$choice" 2>&1) || result=$? ;;
        *) return 0 ;;
    esac
    dialog_msgbox 'SX1262 mode' "$output" 16 76
    return "$result"
}

_sx1262_clock_menu() {
    local status action grid source request description hz output rc=0
    local -a options=()
    status=$(_sx1262_mode_cli spi 2>&1) || status="Current setting unavailable: $status"
    action=$(dialog_menu 'SPI bus clock' "$status" 21 78 6 -- \
        hat 'Choose from the SX1262 frequency grid' custom 'Enter a request in Hz' \
        default 'Restore the profile default' spi0 'Configure SPI0 devices' \
        spi1 'Configure SPI1 devices') || return 0
    case "$action" in
        custom) hz=$(dialog_inputbox 'SX1262 SPI request' 'Clock in Hz for the next backend start' '' 10 72) || return 0 ;;
        default) hz=default ;;
        spi0|spi1) module_spi_clocks select "$action"; return ;;
        hat)
            grid=$(_sx1262_mode_cli spi-grid "$action" --menu 2>&1) || { dialog_msgbox 'SPI clock grid' "$grid" 12 76; return 1; }
            source=${grid%%$'\n'*}
            while IFS=$'\t' read -r request description; do
                [[ $request =~ ^[0-9]+$ ]] && options+=("$request" "$description")
            done <<< "$grid"
            if (( ${#options[@]} == 0 )); then dialog_msgbox 'SPI clock grid' "$source. No in-range clock in this snapshot." 12 76; return 0; fi
            hz=$(dialog_menu 'SX1262 SPI request (Hz)' "$source. Choose a request for the next start." 21 78 10 -- "${options[@]}") || return 0 ;;
        *) return 0 ;;
    esac
    output=$(_sx1262_mode_cli spi "$hz" 2>&1) || rc=$?
    dialog_msgbox 'SX1262 SPI request' "$output" 15 78
    return "$rc"
}
