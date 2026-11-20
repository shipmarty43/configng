module_options+=(
    ["module_spi_clocks,feature"]="module_spi_clocks"
    ["module_spi_clocks,desc"]="Per-device SPI boot clocks for Orange Pi Zero 2W"
    ["module_spi_clocks,example"]="select list status grid set default default-all backups rollback"
    ["module_spi_clocks,group"]="Hardware"
    ["module_spi_clocks,status"]="Preview"
)

_spi_clocks_tool() {
    python3 "${script_dir:-/usr/bin}/../share/armbian-config/spi_devices.py" "$@"
}

_spi_clocks_validate_config() (
    local conf=$1 tmp
    tmp=$(mktemp -d) || return 1
    trap 'rm -rf "$tmp"' EXIT
    _zero2w_overlay_prepare base "$conf" "$tmp/base" spi-clocks '' &&
        _zero2w_overlay_prepare compose "$conf" "$tmp/effective" spi-clocks '' &&
        _spi_clocks_tool "$tmp/base" "$conf" verify "$tmp/effective" "$(_ups_dfr_boot)/overlay-user"
)

_spi_clocks_read() (
    local root conf temp
    root=$(_ups_dfr_boot)
    conf="$root/armbianEnv.txt"
    temp=$(mktemp) || return 1
    trap 'rm -f "$temp"' EXIT
    _zero2w_overlay_prepare base "$conf" "$temp" spi-clocks '' &&
        _spi_clocks_tool "$temp" "$conf" "$@"
)

# Called inside the shared boot-config transaction with its overlay lock held.
_spi_clocks_prepare() {
    local action=$1 before=$2 after=$3 base="${2%/*}/base.dtb"
    if [[ $action == default-all ]]; then
        _spi_clocks_tool /dev/null "$before" default-all "$after"
        return
    fi
    _zero2w_overlay_prepare base "$before" "$base" spi-clocks '' || return 1
    _spi_clocks_tool "$base" "$before" "$action" "${spi_args[@]}" "$after" "$(_ups_dfr_boot)/overlay-user"
}

_spi_clocks_menu() {
    local bus=${1:-} cs devices desc choice status result hz data id rc=0
    local -a opts=()
    if [[ -z $bus ]]; then
        bus=$(dialog_menu 'SPI device clocks' 'Choose a physical controller on the Zero 2W.' 14 74 4 -- \
            spi0 'SPI0' spi1 'SPI1' rollback 'Restore a previous boot configuration' default-all 'Clear all SPI device clock overrides') || return 0
    fi
    if [[ $bus == default-all ]]; then
        dialog_yesno 'Restore device clocks' 'Use the board defaults for every managed chip select on the next boot?' 'Restore' 'Cancel' 10 72 || return 0
        result=$(module_spi_clocks default-all 2>&1) || rc=$?
    elif [[ $bus == rollback ]]; then
        data=$(module_spi_clocks backups) || return 1
        while read -r id; do [[ -z $id ]] || opts+=("$id" 'Restore saved selection'); done <<< "$data"
        if (( ! ${#opts[@]} )); then dialog_msgbox 'SPI device clocks' 'No SPI clock backups.' 9 65; return 0; fi
        id=$(dialog_menu 'SPI clock rollback' 'Choose a saved change.' 16 70 8 -- "${opts[@]}") || return 0
        result=$(module_spi_clocks rollback "$id" 2>&1) || rc=$?
    else
        devices=$(_spi_clocks_read list "$bus" 2>&1) || { dialog_msgbox 'SPI device clocks' "$devices" 12 74; return 1; }
        while IFS=$'\t' read -r cs desc; do [[ -z $cs ]] || opts+=("$cs" "CS$cs  $desc"); done <<< "$devices"
        local prompt='Select a chip select in the next-boot configuration.'
        if (( ! ${#opts[@]} )); then prompt="No enabled devices on ${bus^^}. Check the selected board overlays."; fi
        opts+=(controller 'Inspect full controller frequency grid')
        cs=$(dialog_menu "${bus^^} devices" "$prompt" 16 76 8 -- "${opts[@]}") || return 0
        if [[ $cs == controller ]]; then
            data=$(_sx1262_mode_cli spi-grid "$bus" --menu 2>&1) || { dialog_msgbox 'SPI clock grid' "$data" 10 74; return 1; }
            opts=()
            while IFS=$'\t' read -r hz desc; do [[ $hz =~ ^[0-9]+$ ]] && opts+=("$hz" "$desc"); done <<< "$data"
            if (( ${#opts[@]} )); then
                dialog_menu 'Controller clock grid (Hz)' "${data%%$'\n'*}. Read-only." 21 78 10 -- "${opts[@]}" >/dev/null || :
            fi
            return 0
        fi
        while IFS=$'\t' read -r id desc; do
            if [[ $bus == spi1 && $cs == 0 && $id == "$cs" && $desc == *' (SXMD01)' ]]; then
                _sx1262_clock_menu
                return
            fi
        done <<< "$devices"
        status=$(_spi_clocks_read status "$bus" "$cs" 2>&1) || status="Status unavailable: $status"
        choice=$(dialog_menu "${bus^^} CS$cs" "$status" 18 78 5 -- grid 'Choose a clock from the divider grid' \
            custom 'Enter a clock in Hz' default 'Restore the board default') || return 0
        case "$choice" in
            grid)
                data=$(_spi_clocks_read grid "$bus" "$cs" 2>&1) || { dialog_msgbox 'SPI clock grid' "$data" 10 74; return 1; }
                opts=()
                while IFS=$'\t' read -r hz desc; do [[ $hz =~ ^[0-9]+$ ]] && opts+=("$hz" "$desc"); done <<< "$data"
                if (( ! ${#opts[@]} )); then dialog_msgbox 'SPI clock grid' 'No in-range grid values.' 9 65; return 0; fi
                hz=$(dialog_menu 'SPI clock in Hz' "${data%%$'\n'*}" 21 78 10 -- "${opts[@]}") || return 0 ;;
            custom) hz=$(dialog_inputbox 'SPI device clock' 'Request in Hz for the next Linux boot.' '' 10 74) || return 0 ;;
            default) ;;
            *) return 0 ;;
        esac
        if [[ $choice == default ]]; then
            result=$(module_spi_clocks default "$bus" "$cs" 2>&1) || rc=$?
        else
            result=$(module_spi_clocks set "$bus" "$cs" "$hz" 2>&1) || rc=$?
        fi
    fi
    dialog_msgbox 'SPI device clocks' "$result" 14 78
    return "$rc"
}

module_spi_clocks() {
    local action=${1:-select} backup
    local -a spi_args=("${@:2}")
    case "$action" in
        select) _spi_clocks_menu "${2:-}" ;;
        grid)
            if [[ $# == 2 && ( $2 == spi0 || $2 == spi1 ) ]]; then
                _sx1262_mode_cli spi-grid "$2"
            else
                _spi_clocks_read "$@"
            fi ;;
        list|status) _spi_clocks_read "$@" ;;
        set|default|default-all|rollback)
            _ups_dfr_board || { echo "Expected Orange Pi Zero 2W." >&2; return 1; }
            if [[ $action == default-all && $# != 1 ]]; then return 2; fi
            if [[ $action == rollback ]]; then
                [[ $# == 2 ]] || return 2
            fi
            _zero2w_overlay_change "$action" spi-clocks _spi_clocks_prepare "${2:-}" ;;
        backups)
            for backup in "$(_ups_dfr_boot)"/armbianEnv.txt.spi-clocks-backups/change.*; do
                [[ ! -d $backup ]] || echo "${backup##*/}"
            done ;;
        *) echo 'Expected select, list BUS, status|grid|default BUS CS, set BUS CS HZ, backups or rollback change.ID.' >&2; return 2 ;;
    esac
}
