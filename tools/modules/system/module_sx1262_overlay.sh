module_options+=(
    ["module_sx1262_overlay,feature"]="module_sx1262_overlay"
    ["module_sx1262_overlay,desc"]="Waveshare SPI SX1262 HAT on Orange Pi Zero 2W"
    ["module_sx1262_overlay,example"]="select status enable disable rollback help"
    ["module_sx1262_overlay,group"]="Kernel"
    ["module_sx1262_overlay,status"]="Preview"
    ["module_sx1262_overlay,author"]="@shipmarty43"
    ["module_sx1262_overlay,maintainer"]="@shipmarty43"
)
function _sx1262_validate() {
    local dt="$1" bus=/soc/spi@5011000 pio=/soc/pinctrl@300b000 node pins cs mux child state hz
    node="$bus/radio@0"; pins="$pio/spi1-pins"
    cs=$(fdtget -t x "$dt" "$pio" phandle) && mux=$(fdtget -t x "$dt" "$pins" phandle) || return 1
    local board
    board=" $(fdtget "$dt" / compatible) " || return 1
    [[ "$board" == *' xunlong,orangepi-zero2w '* && "$board" == *' allwinner,sun50i-h618 '* ]] || return 1
    hz=$(fdtget -t u "$dt" "$node" spi-max-frequency) || return 1
    [[ $hz =~ ^[0-9]{1,8}$ ]] && (( 10#$hz >= 3000 && 10#$hz <= 16000000 )) || {
        echo 'Expected a Waveshare SX1262 DT clock ceiling within 3000..16000000 Hz.' >&2; return 1;
    }
    state=$(fdtget -d okay "$dt" "$node" status) || return 1
    [[ "$state" =~ ^(ok|okay)$ && "$(fdtget "$dt" "$bus" status)" == okay &&
       "$(fdtget -t x "$dt" "$bus" cs-gpios)" == "$cs 8 3 1" &&
       "$(fdtget "$dt" "$bus" num-cs)" == 1 && "$(fdtget -t x "$dt" "$bus" pinctrl-0)" == "$mux" &&
       "$(fdtget "$dt" "$pins" pins)" == 'PH6 PH7 PH8' && "$(fdtget "$dt" "$pins" function)" == spi1 &&
       "$(fdtget "$dt" "$node" compatible)" == 'semtech,sx1262 armbian,spi-dev' &&
       "$(fdtget "$dt" "$node" reg)" == 0 ]] && ! fdtget "$dt" "$node" spi-cs-high >/dev/null 2>&1 || {
        echo 'Expected SX1262 on SPI1 PH6/PH7/PH8 with kernel CS0 on PI3.' >&2; return 1;
    }
    for child in $(fdtget -l "$dt" "$bus"); do
        [[ "$child" != radio@0 ]] || continue
        if fdtget "$dt" "$bus/$child" reg >/dev/null 2>&1 && [[ "$(fdtget -d okay "$dt" "$bus/$child" status)" =~ ^(ok|okay)$ ]]; then
            echo "SPI1 conflict with $child on the single-CS HAT profile." >&2; return 1
        fi
    done
}
function _sx1262_prepare() { _zero2w_overlay_prepare "$@" sx1262 opi-zero2w-sx1262; }
function _sx1262_class() { echo /sys/class/spidev; }
function module_sx1262_overlay() {
    local action="${1:-select}" boot dt endpoint choice output backup
    _ups_dfr_board || { echo 'Expected Orange Pi Zero 2W.' >&2; return 1; }
    boot=$(_ups_dfr_boot); dt=$(_ups_dfr_dt)
    case "$action" in
        status)
            local next=disabled live=unbound
            [[ -r "$boot/armbianEnv.txt" ]] || return 1
            if awk '/^user_overlays=/ {sub(/^user_overlays=/,""); for(i=1;i<=NF;i++) if($i=="opi-zero2w-sx1262") hit=1} END {exit !hit}' "$boot/armbianEnv.txt"; then next=enabled; fi
            for endpoint in "$(_sx1262_class)"/spidev*.0; do
                if [[ "$endpoint/device/of_node" -ef "$dt/soc/spi@5011000/radio@0" ]]; then live="/dev/${endpoint##*/}"; fi
            done
            printf 'Next boot: %s\nLive SPI endpoint: %s\n' "$next" "$live"
            for backup in "$boot"/armbianEnv.txt.sx1262-backups/change.*; do [[ ! -d "$backup" ]] || echo "Backup: ${backup##*/}"; done ;;
        enable|disable|rollback) _zero2w_overlay_change "$action" sx1262 _sx1262_prepare "${2:-}" ;;
        select)
            choice=$(dialog_menu 'Waveshare SX1262' 'SPI1 radio overlay on Orange Pi Zero 2W' 16 74 5 \
                status 'Current endpoint, next boot and backups' enable 'Enable installed HAT overlay' \
                disable 'Disable HAT overlay' rollback 'Restore a saved boot configuration') || return 0
            if [[ "$choice" == rollback ]]; then
                local -a options=()
                for backup in "$boot"/armbianEnv.txt.sx1262-backups/change.*; do
                    [[ ! -d "$backup" ]] || options+=("${backup##*/}" "$(stat -c %y "$backup/before")")
                done
                if (( ${#options[@]} == 0 )); then dialog_msgbox 'Waveshare SX1262' 'No saved changes.' 9 60; return; fi
                backup=$(dialog_menu 'Rollback' 'Select a matching backup' 16 76 6 "${options[@]}") || return 0
            fi
            local rc=0
            output=$(module_sx1262_overlay "$choice" "$backup" 2>&1) || rc=$?
            dialog_msgbox 'Waveshare SX1262' "$output" 18 80
            return "$rc" ;;
        help) echo 'sx1262 select|status|enable|disable|rollback change.ID. Install opi-zero2w-sx1262.dtbo under /boot/overlay-user first.' ;;
        *) return 1 ;;
    esac
}
