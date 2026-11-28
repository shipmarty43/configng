#!/bin/bash
# Run as a oneshot service in the disposable board root filesystem.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C DEBIAN_FRONTEND=noninteractive
cd /run/qa
phase=$(sed -n 's/.*qa_phase=\([a-z]*\).*/\1/p' /proc/cmdline)
exec >"result/$phase.log" 2>&1
finish() {
    rc=$?; trap - EXIT
    echo "guest exit $rc"; if (( rc == 0 )); then echo PASS > "result/$phase.pass"; fi
    sync; systemctl poweroff --no-block; exit "$rc"
}
trap finish EXIT
. /etc/armbian-image-release
echo "$BOARD $(uname -r) $phase"
read -r expected_board pkg rel original updated stocksha patchedsha < input/manifest
[[ $BOARD == "$expected_board" && $(uname -r) == "$rel" ]]
verify_pkg() {
    local ver=$1 sha=$2
    [[ $(dpkg-query -W -f='${db:Status-Status} ${Version}' "$pkg") == "installed $ver" ]]
    test "$(readlink -f /boot/Image)" = "/boot/vmlinuz-$rel"
    echo "$sha  /boot/Image" | sha256sum -c -
    test -s "/boot/System.map-$rel" && test -s "/lib/modules/$rel/modules.dep"
    test -s "/boot/initrd.img-$rel" && test -s "/boot/uInitrd-$rel"
    [[ $(readlink -f /boot/uInitrd) == "/boot/uInitrd-$rel" ]]
    python3 /run/qa/input/ramdisk.py "$rel"
    local md="/var/lib/dpkg/info/$pkg.md5sums"
    (cd / && awk '$2 ~ /\.ko(\.(xz|gz|zst))?$/ || $2 ~ /^boot\/(config|vmlinuz|System.map)-/' "$md" | md5sum --quiet -c -)
    echo "dpkg $ver; kernel, config, System.map and all shipped modules verified"
}
boot_data() {
    local dtb
    case "$BOARD" in
        orangepizero2w) dtb=sun50i-h618-orangepi-zero2w.dtb ;;
        orangepizero3w) dtb=sun60i-a733-orangepi-zero3w.dtb ;;
        *) return 1 ;;
    esac
    sha256sum /boot/armbianEnv.txt "/boot/dtb/allwinner/$dtb" /boot/boot.scr
}
verify_boot() {
    if [[ -f input/profile.sh ]]; then
        kit_compare_env result/base.env
        grep -v '  /boot/armbianEnv.txt$' result/base.sha | sha256sum -c -
    else
        sha256sum -c result/base.sha
    fi
}
symbols() { grep -q ' header_pwm_profiles_show' /proc/kallsyms; }
upgrade() {
    dpkg --force-confold -i "$1"
    dpkg --audit "$pkg" > result/dpkg-audit
    test ! -s result/dpkg-audit
}
modprobe pwm-fan
test -d /sys/module/pwm_fan
modprobe -r pwm-fan
echo "pwm-fan loaded and unloaded on the running kernel"
if [[ -f input/profile.sh ]]; then . input/profile.sh; fi
if [[ $phase == before || $phase == install ]]; then
    ! symbols || exit 1
    verify_pkg "$original" "$stocksha"
    boot_data > result/base.sha
    cp /boot/armbianEnv.txt result/base.env
    if [[ $phase == install ]]; then
        if [[ -f input/profile.sh ]]; then bash input/kit/apply.sh install; else upgrade input/current.deb; fi
        verify_pkg "$updated" "$patchedsha"
        verify_boot
        if [[ -f input/profile.sh ]]; then kit_save; fi
        cp /boot/Image result/installed.Image
    fi
elif [[ $phase == downgrade ]]; then
    symbols
    if [[ -f input/profile.sh ]]; then kit_check; kit_undo; fi
    verify_pkg "$updated" "$patchedsha"
    verify_boot
    if [[ -f input/profile.sh ]]; then bash input/kit/apply.sh rollback-kernel; else upgrade input/stock.deb; fi
    verify_pkg "$original" "$stocksha"
    verify_boot
    cp /boot/Image result/restored.Image
elif [[ $phase == restored ]]; then
    ! symbols || exit 1
    verify_pkg "$original" "$stocksha"; verify_boot
else exit 2; fi
