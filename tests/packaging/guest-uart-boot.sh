#!/usr/bin/env bash
# Runs only inside an isolated package-test guest.
set -euo pipefail
media=/mnt/opi-release
proof=/var/lib/opi-package-proof
boot=/boot/armbianEnv.txt
shared=/opt/armbian-config-zero2w/share/armbian-config
test -f "$media/uart-boot"
test "$(ls /sys/class/net)" = lo
unit=opi-zero2w-uart@ttyS1.service
if [[ $1 == prepare ]]; then
    cp "$boot" "$proof/uart-before"
    armbian-config-zero2w --api module_h616_uart enable uart3
    python3 "$shared/h616_uart.py" save uart3 57600 7 even 2
    grep -Fx 'user_overlays=opi-uart3-header' "$boot"
    fdtoverlay -i /boot/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb -o "$proof/uart.dtb" \
        /boot/overlay-user/opi-uart3-header.dtbo
    test "$(fdtget "$proof/uart.dtb" /soc/pinctrl@300b000/opi-uart3-header-pins function)" = uart3
    udevadm verify /usr/lib/udev/rules.d/80-opi-zero2w-uart.rules
    systemd-analyze verify "$unit"
    PYTHONPATH="$shared" python3 "$media/guest-uart-boot.py" fixture "$proof/uart.dtb"
    mkdir -p "/etc/systemd/system/$unit.d"
    # Only the DT/sysfs topology is substituted. The udev add event, rule,
    # unit, profile, ownership checks and /dev/ttyS1 file operations are real.
    printf '[Service]\nBindReadOnlyPaths=%s:/sys\n' "$proof/uart-test-sys" > "/etc/systemd/system/$unit.d/twin.conf"
    cat /proc/sys/kernel/random/boot_id > "$proof/uart-boot-id"
    echo PASS-UART-PREPARED
    exit
fi
test "$(cat /proc/sys/kernel/random/boot_id)" != "$(cat "$proof/uart-boot-id")"
for _ in $(seq 1 30); do
    stamp=$(systemctl show "$unit" -P ExecMainExitTimestampMonotonic)
    [[ $stamp == 0 || -z $stamp ]] || break
    sleep 1
done
journalctl --no-pager -b -u "$unit" -o cat | tee "$proof/uart-service.log"
grep -Fxq 'Restored uart3 on ttyS1' "$proof/uart-service.log"
PYTHONPATH="$shared" python3 "$media/guest-uart-boot.py" verify
python3 "$shared/h616_uart.py" forget uart3
test ! -e /etc/armbian-config/uart/uart3.json
backup=(/boot/armbianEnv.txt.uart-backups/change.*)
armbian-config-zero2w --api module_h616_uart boot-rollback "${backup[0]##*/}"
cmp "$proof/uart-before" "$boot"
python3 "$media/guest_menu.py" UART01 'Header overlays and saved boot settings'
echo PASS-UART-BOOT-RESTORE
