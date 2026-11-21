#!/usr/bin/env bash
# Run only on the guest's private qcow2 layer. No GPIO or physical PWM passthrough.
set -eo pipefail
test -f /mnt/opi-release/pwm-boot
test "$(ls /sys/class/net)" = lo
prefix=/opt/armbian-config-zero2w; proof=/var/lib/opi-package-proof
script_dir="$prefix/bin"; declare -A module_options
source "$prefix/lib/armbian-config/config.system.sh"
set -u
pwm() { module_h616_pwm "$@"; }
reject() { if "$@"; then echo "Unexpected success: $*" >&2; exit 1; fi; }
conf=/boot/armbianEnv.txt
if [[ $1 == prepare ]]; then
    cp "$conf" "$proof/pwm-before"
    # Include the pre-multichannel syntax for PWM1.
    armbian-config-zero2w --api module_h616_pwm set 1000 25 normal
    pwm pwm2 set 2000 37.5 inversed; pwm pwm3 set 10000 60 normal; pwm pwm4 set 20000 50 normal
    for n in 1 2 3 4; do pwm "pwm$n" route "PI$((10+n))"; done
    cp "$conf" "$proof/pwm-all"
    reject module_h616_uart enable uart4
    reject pwm pwm3 route PH0
    reject pwm pwm4 route PH1
    cmp "$conf" "$proof/pwm-all"
    pwm pwm2 route PH2
    reject module_h616_uart enable uart5
    pwm pwm2 route PI12
    cmp "$conf" "$proof/pwm-all"
    systemd-analyze verify opi-zero2w-pwm.service opi-zero2w-pwm@2.service opi-zero2w-pwm@3.service opi-zero2w-pwm@4.service
    cat /proc/sys/kernel/random/boot_id > "$proof/pwm-boot-id"
    echo PASS-PWM-PREPARED
    exit 0
fi
test "$(cat /proc/sys/kernel/random/boot_id)" != "$(cat "$proof/pwm-boot-id")"
pwm routes > "$proof/pwm-routes"
for n in 1 2 3 4; do grep -F "Next boot: PI$((n+10))," "$proof/pwm-routes"; done
python3 - <<'PY'
import json
from pathlib import Path
for n,(freq,duty,level) in enumerate(((1000,"25","normal"),(2000,"37.5","inversed"),(10000,"60","normal"),(20000,"50","normal")),1):
    p=Path(f"/etc/armbian-config/pwm{n}.json")
    assert json.loads(p.read_text())==dict(hz=freq,duty=duty,polarity=level)
    print("Saved PWM", n, freq, duty, level)
PY
for unit in opi-zero2w-pwm.service opi-zero2w-pwm@{2,3,4}.service; do
    if systemctl is-active --quiet "$unit"; then exit 1; fi
done
pwm pwm2 default; test ! -e /etc/armbian-config/pwm2.json
for n in 1 3 4; do test -s "/etc/armbian-config/pwm$n.json"; done
python3 /mnt/opi-release/guest_menu.py PWM001 'Choose a channel'
echo PASS-PWM-BOOT-PROFILES
