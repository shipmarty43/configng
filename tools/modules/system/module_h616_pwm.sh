module_options+=(
    ["module_h616_pwm,feature"]="module_h616_pwm"
    ["module_h616_pwm,desc"]="Configure header PWM1 on PI11 (pin 32)"
    ["module_h616_pwm,example"]="select status set default start restart stop"
    ["module_h616_pwm,group"]="Hardware"
    ["module_h616_pwm,status"]="Preview"
)

_h616_pwm_cli() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/h616_pwm.py" "$@"; }
module_h616_pwm() {
    local data action hz duty polarity result rc=0
    case "${1:-select}" in
        status|set|default) _h616_pwm_cli "$@"; return ;;
        restart)
            _h616_pwm_cli validate || return 1
            systemctl restart opi-zero2w-pwm.service; return ;;
        start|stop) systemctl "$1" opi-zero2w-pwm.service; return ;;
        select) ;;
        *) return 2 ;;
    esac
    data=$(_h616_pwm_cli status 2>&1) || { dialog_msgbox 'PWM1' "$data" 12 74; return 1; }
    action=$(dialog_menu 'Header PWM1' "$data" 19 76 5 -- set 'Save frequency, active duty and polarity' \
        start 'Start saved output on pin 32' restart 'Restart with saved waveform' stop 'Stop output and release channel' default 'Clear saved waveform') || return 0
    if [[ $action == set ]]; then
        hz=$(dialog_inputbox 'PWM frequency' 'Hz (1..1000000)' '' 10 65) || return 0
        duty=$(dialog_inputbox 'PWM active duty' 'Active percent (0..100, up to two decimal places)' '' 10 70) || return 0
        polarity=$(dialog_menu 'PWM polarity' 'Active level' 12 65 2 -- normal 'Active high' inversed 'Active low') || return 0
        result=$(_h616_pwm_cli set "$hz" "$duty" "$polarity" 2>&1) || rc=$?
    else
        result=$(module_h616_pwm "$action" 2>&1) || rc=$?
        if [[ ! $result && $rc == 0 ]]; then result=$(_h616_pwm_cli status); fi
    fi
    dialog_msgbox 'Header PWM1' "$result" 14 76
    return "$rc"
}
