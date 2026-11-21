module_options+=(
    ["module_a733_io,feature"]="module_a733_io"
    ["module_a733_io,desc"]="Manage A733 SPI, I2C and UART header routes"
    ["module_a733_io,group"]="Hardware"
    ["module_a733_io,status"]="Preview"
)

_a733_board() {
    local compat="$(_ups_dfr_dt)/compatible"
    grep -zFxq 'xunlong,orangepi-zero3w' "$compat" && grep -zFxq 'arm,sun60iw2p1' "$compat"
}
_a733_io_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/a733_io.py" "$(_ups_dfr_boot)" "$@"; }
_a733_uart_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/a733_uart.py" "$@"; }
_a733_prepare() { _a733_io_cli "$2" "$1" "${a733_args[@]}" "$3"; }

_a733_menu() {
    local key action cs hz mode data rc=0 id
    local -a options=() params=()
    data=$(module_a733_io list 2>&1) || { dialog_msgbox 'A733 header' "$data" 14 78; return 1; }
    while IFS=$'\t' read -r key desc; do options+=("$key" "$desc"); done <<< "$data"
    key=$(dialog_menu 'Orange Pi Zero 3W header' 'Select a physical route. Pin numbers follow the 40-pin header.' 22 82 12 -- "${options[@]}" grid 'Inspect divider grid for a parent clock' camera 'Camera capture and shared PE0' pinctrl-test 'Vendor pin-test IRQ and shared PB6' rollback 'Restore a saved boot configuration') || return 0
    case "$key" in
        rollback)
            options=()
            while read -r id; do [[ -z $id ]] || options+=("$id" 'Undo recorded boot change'); done < <(module_a733_io backups)
            if (( ! ${#options[@]} )); then dialog_msgbox 'A733 rollback' 'No saved boot changes.' 8 60; return; fi
            id=$(dialog_menu 'A733 rollback' 'Select the change to undo.' 16 70 8 -- "${options[@]}") || return 0
            params=(rollback "$id") ;;
        grid)
            key=$(dialog_menu 'A733 divider grid' 'Choose a controller.' 18 72 8 -- "${options[@]}") || return 0
            hz=$(dialog_inputbox 'Clock source in Hz' 'Supply the actual parent clock or use 24 MHz as an example.' 24000000 11 74) || return 0
            data=$(module_a733_io grid "$key" "$hz" 2>&1) || { dialog_msgbox 'A733 clocks' "$data" 10 75; return 1; }
            local file
            file=$(mktemp) || return 1
            printf '%s\n' "$data" > "$file"
            case ${DIALOG:-dialog} in
                dialog) dialog --title 'Calculated divider grid (Hz)' --textbox "$file" 21 78 || : ;;
                whiptail) whiptail --title 'Calculated divider grid (Hz)' --scrolltext --textbox "$file" 21 78 || : ;;
                *) cat "$file" ;;
            esac
            rm -f -- "$file"
            return ;;
        pinctrl-test)
            action=$(dialog_menu 'Vendor pin test and PB6' 'The vendor test device uses PB6 as a wake IRQ. CS3 needs exclusive use of pin 35.' 15 78 2 -- release 'Disable the vendor test device at next boot' default 'Restore base pin-test setting') || return 0
            if [[ $action == release ]]; then params=(set pinctrl-test release); else params=(default pinctrl-test); fi ;;
        camera)
            action=$(dialog_menu 'Camera and PE0' 'Camera MCLK and header SPI3/UART6 share PE0.' 15 78 3 -- release 'Disable camera capture at next boot' default 'Restore base camera setting') || return 0
            if [[ $action == release ]]; then params=(set camera release); else params=(default camera); fi ;;
        spi2)
            action=$(dialog_menu SPI2 'CLK/MOSI/MISO on 13/5/3. Each attached peripheral needs its own device overlay.' 18 78 6 -- enable 'Use CS0 only (pin 11)' add-cs 'Add a native chip select' remove-cs 'Release a chip-select pin' default 'Restore base route' clock 'Set peripheral frequency and mode' reset-clock 'Restore peripheral settings') || return 0
            case "$action" in
                enable) params=(set spi2 on) ;;
                default) params=(default spi2) ;;
                add-cs|remove-cs)
                    cs=$(dialog_menu SPI2 'Native chip-select pin' 13 72 3 -- 1 'CS1 PB4 / pin 7' 2 'CS2 PB5 / pin 12' 3 'CS3 PB6 / pin 35') || return 0
                    params=("$action" "$cs") ;;
                reset-clock|clock)
                    cs=$(dialog_menu SPI2 'Declared peripheral to configure' 14 72 4 -- 0 'CS0 / pin 11' 1 'CS1 / pin 7' 2 'CS2 / pin 12' 3 'CS3 / pin 35') || return 0
                    if [[ $action == reset-clock ]]; then
                        params=(default "spi2-cs$cs")
                    else
                        hz=$(dialog_inputbox SPI2 'Maximum Hz for the selected peripheral.' 500000 10 72) || return 0
                        mode=$(dialog_menu SPI2 'SPI mode (CPOL / CPHA)' 14 66 4 -- 0 '0 / 0' 1 '0 / 1' 2 '1 / 0' 3 '1 / 1') || return 0
                        params=(set "spi2-cs$cs" "$hz" "$mode")
                    fi ;;
            esac ;;
        spi3)
            cs=$(dialog_menu SPI3 'Choose the physical chip select.' 12 65 2 -- 0 'CS0 on pin 24' 1 'CS1 on pin 26') || return 0
            action=$(dialog_menu SPI3 'Next-boot settings for this endpoint.' 12 72 2 -- set 'Enable and configure' default 'Restore base configuration') || return 0
            params=("$action" "spi3-cs$cs")
            if [[ $action == set ]]; then
                hz=$(dialog_inputbox SPI3 'Peripheral maximum Hz (stock 500000). Use the limit of the attached device.' 500000 11 76) || return 0
                mode=$(dialog_menu SPI3 'SPI mode (CPOL / CPHA)' 14 66 4 -- 0 '0 / 0' 1 '0 / 1' 2 '1 / 0' 3 '1 / 1') || return 0
                params+=("$hz" "$mode")
            fi ;;
        i2c*)
            hz=$(dialog_menu "$key" 'Next-boot SCL for the entire header bus.' 14 66 3 -- 100000 '100 kHz' 400000 '400 kHz' default 'Restore base configuration') || return 0
            if [[ $hz == default ]]; then params=(default "$key"); else params=(set "$key" "$hz"); fi ;;
        uart*)
            options=()
            case $key in
                uart2) options+=(rtscts 'Hardware RTS/CTS on pins 5/3') ;;
                uart6) options+=(rtscts 'Hardware RTS/CTS on pins 19/21') ;;
            esac
            action=$(dialog_menu "$key" 'Route and line settings.' 17 72 6 -- "${options[@]}" enable 'Enable at next boot' default 'Restore base route' save 'Save baud and framing for device discovery' show 'Inspect saved framing' forget 'Clear saved framing') || return 0
            case "$action" in
                enable) params=(set "$key" on) ;;
                rtscts) params=(set "$key" rtscts) ;;
                save) data=$(_uart_get_framing "$key") || return 0; read -r -a params <<< "$data"; params=(save "$key" "${params[@]}") ;;
                *) params=("$action" "$key") ;;
            esac ;;
        *) return 1 ;;
    esac
    data=$(module_a733_io "${params[@]}" 2>&1) || rc=$?
    dialog_msgbox 'A733 header' "${data:-Saved}" 14 78
    return "$rc"
}

module_a733_io() {
    local action=${1:-select} root folder
    local -a a733_args=("${@:2}")
    _a733_board || { echo 'Expected Armbian Orange Pi Zero 3W with A733.' >&2; return 1; }
    root=$(_ups_dfr_boot)
    case "$action" in
        select) _a733_menu ;;
        grid) _a733_io_cli "$root/armbianEnv.txt" "$@";;
        list) _a733_io_cli "$root/armbianEnv.txt" list ;;
        save|show|forget) _a733_uart_cli "$@" ;;
        backups) for folder in "$root"/armbianEnv.txt.a733-io-backups/change.*; do [[ ! -d $folder ]] || echo "${folder##*/}"; done ;;
        set|default|rollback|add-cs|remove-cs)
            [[ -f $root/boot.scr && ! -e $root/extlinux/extlinux.conf ]] &&
                grep -aFq 'armbianEnv.txt' "$root/boot.scr" &&
                grep -aFq 'overlay-user/${overlay_file}.dtbo' "$root/boot.scr" || { echo 'Unrecognized Armbian overlay boot route.' >&2; return 1; }
            _zero2w_overlay_change "$action" a733-io _a733_prepare "${2:-}" ;;
        *) return 2 ;;
    esac
}
