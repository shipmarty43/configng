module_options+=(
    ["module_gnss,feature"]="module_gnss"
    ["module_gnss,desc"]="Select a local GNSS source on Orange Pi Zero 2W"
    ["module_gnss,example"]="select status auto waveshare modem off prefer device"
    ["module_gnss,group"]="Hardware"
    ["module_gnss,status"]="Preview"
    ["module_gnss,author"]="@shipmarty43"
    ["module_gnss,maintainer"]="@shipmarty43"
)
function _gnss_bin() { /usr/local/bin/opi-gnss "$@"; }
function module_gnss() {
    local action="${1:-select}" choice value rc=0
    case "$action" in
        status) _gnss_bin status ;;
        off) _gnss_bin configure --mode off && systemctl disable --now opi-gnss.service ;;
        auto|waveshare|modem)
            _gnss_bin configure --mode "$action" && systemctl enable opi-gnss.service && systemctl restart opi-gnss.service ;;
        prefer|device)
            [[ -n "${2:-}" ]] || return 1
            _gnss_bin configure "--$action" "$2" && systemctl try-restart opi-gnss.service ;;
        select)
            choice=$(dialog_menu 'GNSS receivers' 'Choose a receiver or inspect the current fix' 18 78 8 \
                status 'Selected fix and receiver health' auto 'Automatic failover' waveshare 'Waveshare L76K only' \
                modem 'SIM7600 via ModemManager only' off 'Stop local selection' \
                prefer 'Preferred source in Auto' device 'Waveshare UART path as registered in gpsd') || return 0
            case "$choice" in
                prefer) value=$(dialog_menu 'Preferred GNSS' 'Select preferred receiver' 12 64 2 waveshare 'Waveshare' modem 'SIM7600') || return 0 ;;
                device) value=$(dialog_inputbox 'Waveshare GNSS' 'Exact device path from gpsd' '' 12 72) || return 0 ;;
            esac
            value=$(module_gnss "$choice" "$value" 2>&1) || rc=$?
            dialog_msgbox 'GNSS receivers' "${value:-Settings applied.}" 22 80
            return "$rc" ;;
        help) echo 'module_gnss select|status|auto|waveshare|modem|off|prefer waveshare|modem|device /dev/UART' ;;
        *) return 1 ;;
    esac
}
