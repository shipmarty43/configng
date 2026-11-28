# Sourced by the VM guest lifecycle test. Only the packaged entry points edit /boot.
kit_api() { armbian-config-zero2w --api "$@"; }
kit_backup() { sed -n 's/.*Backup: .*\/\(change\.[[:alnum:]]*\).*/\1/p' | tail -1; }
kit_save() {
    local first=0
    if [[ $BOARD == orangepizero2w ]]; then
        first=2
        kit_api module_h616_pwm pwm2 route PI12 | kit_backup > result/route2
        kit_api module_h616_pwm pwm3 route PI13 | kit_backup > result/route3
    fi
    python3 input/menu.py
    kit_api module_pwm_modes backups | tail -1 > result/pair-id
    grep -Eq "opi-pwmx-.*-pair-$first-500" /boot/armbianEnv.txt
    if [[ $BOARD == orangepizero3w ]]; then
        kit_api module_pwm_modes set fan 5 0 64 128 192 255 | kit_backup > result/fan-id
    fi
    kit_api module_pwm_modes verify
    sha256sum /boot/armbianEnv.txt /boot/overlay-user/opi-pwmx-*.dtbo > result/profile.sha
}
kit_check() {
    local module
    sha256sum -c result/profile.sha
    kit_api module_pwm_modes verify
    kit_api module_pwm_modes list | grep -F pair
    for module in opi_header_gpio opi_i2c_recovery; do modprobe "$module"; test -d "/sys/module/$module"; done
    if [[ $BOARD == orangepizero2w ]]; then modprobe dfr0528_battery; test -d /sys/module/dfr0528_battery; fi
    if [[ $BOARD == orangepizero3w ]]; then kit_api module_pwm_modes list | grep '0-64-128-192-255'; fi
    echo "PASS saved profile and packaged helpers after native reboot"
}
kit_undo() {
    if [[ $BOARD == orangepizero3w ]]; then kit_api module_pwm_modes rollback "$(cat result/fan-id)"; fi
    kit_api module_pwm_modes rollback "$(cat result/pair-id)"
    if [[ $BOARD == orangepizero2w ]]; then
        kit_api module_h616_pwm boot-rollback "$(cat result/route3)"
        kit_api module_h616_pwm boot-rollback "$(cat result/route2)"
    fi
}
