#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l SYSTEMD_PAGER=cat PYTHONDONTWRITEBYTECODE=1 PYTHON_CPU_COUNT=1
media=/mnt/opi-release
proof=/var/lib/opi-package-proof
mkdir -p "$proof"
cd "$media"
pkg=(armbian-config-zero2w opi-zero2w-mesh-runtime opi-zero2w-mesh)
fail() {
    echo "GUEST-ERROR line=$1"
    journalctl --no-pager -n 8 -u opi-reticulum -u opi-lxmf -u opi-meshtastic-sim -u opi-meshtastic-mail -o cat || :
}
trap 'fail "$LINENO"' ERR
test "$(dpkg --print-architecture)" = arm64
test -z "$(find /dev -maxdepth 1 \( -name 'spidev*' -o -name 'gpiochip*' \) -print)"
test "$(ls /sys/class/net)" = lo
test "$(cat /sys/firmware/devicetree/base/soc/spi@5011000/radio@0/status | tr -d '\000')" = disabled
test -z "$(find /etc/systemd/system -name 50-devices.conf -print)"
grep -q "^BOARD=orangepizero2w$" /etc/armbian-release
echo "GUEST $(uname -m) kernel=$(uname -r) board=$(sed -n 's/^BOARD=//p' /etc/armbian-release)"
verify_version() {
    for name in "${pkg[@]}"; do
        deb=$(find "$media/$1" -name "${name}_*.deb" -print -quit)
        test "$(dpkg-query -W -f='${db:Status-Status} ${Version}' "$name")" = "installed $(dpkg-deb -f "$deb" Version)"
    done
    test -z "$(dpkg --audit)"
    sha256sum --check "$proof/stock.sha"
    systemctl is-active --quiet opi-reticulum-radio.service && return 1
    systemctl is-active --quiet opi-meshtastic-radio.service && return 1
    test ! -s /etc/armbian-config/sx1262-profile || grep -Fxq no-radio /etc/armbian-config/sx1262-profile
    test ! -e /etc/opi-mesh/allow-radio
    echo "DPKG-PASS $1 $(dpkg-query -W -f='${Version}' armbian-config-zero2w)"
}
runtime_tools() {
    /opt/opi-mesh/venv/bin/python -c 'import RNS,LXMF,meshtastic,gpiod,dbus_fast,google.protobuf,cryptography; print("IMPORT-PASS",RNS.__version__,LXMF.__version__)'
    test "$(sha256sum /opt/opi-mesh/venv/lib/python3.14/site-packages/RNS/Interfaces/RNodeInterface.py | cut -d" " -f1)" = "$1"
    test -z "$(ldd /opt/opi-mesh/meshtasticd | grep "not found" || :)"
}
baseline=ca012e16ee6070464bf54dc5c03f3b49b1e65fc7ff7ec9890caba475a8a5c09d
candidate=1024690fe61c532ce6ac25c9afec2397850355d32bb83caef72441458d0afef9
# The original pre-diagnostics baseline used the unpatched decoder.
previous_rev=$(dpkg-deb -f "$media"/previous/opi-zero2w-mesh-runtime_*.deb X-Source-Revision)
if [[ $previous_rev != 7a48de26* ]]; then baseline=$candidate; fi
py=/opt/opi-mesh/venv/bin/python
shared=/opt/armbian-config-zero2w/share/armbian-config
feature_files() {
    for path in "$shared/h616_spi_clock.py" "$shared/sx1262_diagnostics.py" /opt/opi-mesh/rnode_metrics.py; do
        if [[ -f $path ]]; then printf '%s\n' "$path"; fi
    done
}
finish_upgrade() {
    if [[ -d $media/mesh-recovery ]]; then
        export PYTHONPATH=/opt/opi-mesh:$shared
        "$py" -c 'import lxmf_mailbox as m, sx1262_tx as tx; assert m.__file__.startswith("/opt/opi-mesh/") and tx.__file__.startswith("/opt/opi-mesh/")'
        OPI_TWIN_WAIT_SCALE=3 "$py" -Bu "$media/mesh-recovery/check_lxmf_recovery.py"
        verify_version current
        echo PASS-PACKAGED-LXMF-RECOVERY
    fi
    bash "$media/apply.sh" previous
    verify_version previous
    runtime_tools "$baseline"
    "$py" guest_state.py downgraded
    armbian-config-zero2w --api module_sx1262_mode spi | grep -F '500000 Hz'
    feature_files > "$proof/downgraded.files"
    cmp "$proof/baseline.files" "$proof/downgraded.files"
    cat /proc/sys/kernel/random/boot_id > "$proof/reboot"
    echo PASS-INSTALL-UPGRADE-DOWNGRADE
}
if [[ -f $media/pwm-boot && -s $proof/pwm-boot-id ]]; then
    verify_version current
    bash "$media/guest-pwm-boot.sh" verify
    exit 0
fi
if [[ -f $media/uart-boot && -s $proof/uart-boot-id ]]; then
    verify_version current
    bash "$media/guest-uart-boot.sh" verify
    exit 0
fi
if [[ -e "$proof/reboot" ]]; then
    test "$(cat /proc/sys/kernel/random/boot_id)" != "$(cat "$proof/reboot")"
    verify_version previous
    "$py" guest_state.py reboot-after-downgrade
    armbian-config-zero2w --api module_sx1262_mode spi | grep -F '500000 Hz'
    echo PASS-REBOOT
    exit 0
fi
if [[ -e $media/resume-upgraded ]]; then
    verify_version current
    runtime_tools "$candidate"
    "$py" guest_state.py resumed-upgrade
    finish_upgrade
    exit 0
fi
for p in "${pkg[@]}"; do ! dpkg-query -W "$p" >/dev/null 2>&1 || exit 1; done
for p in /opt/opi-mesh /opt/armbian-config-zero2w /var/lib/opi-lxmf /var/lib/opi-meshtastic-mail /etc/armbian-config/sx1262-spi-hz; do test ! -e "$p"; done
sha256sum /usr/bin/armbian-config > "$proof/stock.sha"
echo CLEAN-IMAGE-VERIFIED
release=previous
decoder=$baseline
if [[ -e $media/fresh-current ]]; then
    release=current
    decoder=$candidate
fi
bash "$media/apply.sh" "$release"
verify_version "$release"
runtime_tools "$decoder"
for unit in opi-reticulum opi-lxmf opi-meshtastic-sim opi-meshtastic-mail; do
    if systemctl is-active --quiet "$unit"; then echo "Unexpected autostart $unit"; exit 1; fi
done
systemd-analyze verify opi-lxmf.service opi-reticulum-radio.service opi-meshtastic-mail.service opi-sx1262-restore.service
if [[ -e $media/pwm-boot ]]; then
    bash "$media/guest-pwm-boot.sh" prepare
    exit 0
fi
if [[ -e $media/uart-boot ]]; then
    bash "$media/guest-uart-boot.sh" prepare
    exit 0
fi
if [[ -e $media/io-current ]]; then
    bash "$media/guest-io.sh"
    echo PASS-FRESH-CURRENT
    exit 0
fi
if [[ $release == current ]]; then
    armbian-config-zero2w --api module_sx1262_mode diagnostics > "$proof/diagnostics"
    grep -F 'Current owner: off' "$proof/diagnostics"
    grep -F 'Next: 2000000 Hz' "$proof/diagnostics"
    if [[ -f $shared/h616_spi_clock.py ]]; then
        armbian-config-zero2w --api module_sx1262_mode spi-grid spi1 > "$proof/grid"
        grep -F $'100000000\t100000000 Hz' "$proof/grid"
        python3 "$shared/sx1262_mode.py" spi 16000000 | grep -F 'Next backend start: 16000000 Hz'
        if python3 "$shared/sx1262_mode.py" spi 16000001; then exit 1; fi
        grep -Fx 16000000 /etc/armbian-config/sx1262-spi-hz
        python3 "$shared/sx1262_mode.py" spi default | grep -F 'Next backend start: 2000000 Hz'
        echo PASS-SPI-GRID
    fi
    if [[ -f $shared/spi_devices.py ]]; then
        cp /boot/armbianEnv.txt "$proof/before-spi.env"
        armbian-config-zero2w --api module_spi_clocks set spi0 0 18000000
        # Compile the actual stock board DT with the boot-selected overlay.
        # The QEMU kernel has its own disabled SPI metadata and no radio.
        name=$(sed -n 's/^user_overlays=//p' /boot/armbianEnv.txt)
        [[ $name == opi-sclk-spi0-cs0-*-18000000 && $name != *" "* ]]
        fdtoverlay -i /boot/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb -o "$proof/spi.dtb" "/boot/overlay-user/$name.dtbo"
        test "$(fdtget -t u "$proof/spi.dtb" /soc/spi@5010000/flash@0 spi-max-frequency)" = 18000000
        id=(/boot/armbianEnv.txt.spi-clocks-backups/change.*)
        test "${#id[@]}" = 1
        armbian-config-zero2w --api module_spi_clocks rollback "${id[0]##*/}"
        cmp "$proof/before-spi.env" /boot/armbianEnv.txt
        python3 guest_menu.py SPI001 'Choose a physical controller'
        echo PASS-SPI-DEVICES
    fi
    echo PASS-FRESH-CURRENT
    exit 0
fi
systemctl start opi-lxmf.service
for i in $(seq 1 120); do
    [[ -s /var/lib/opi-lxmf/address ]] && break
    sleep 1
done
test -s /var/lib/opi-lxmf/address
systemctl start opi-meshtastic-mail.service
for i in $(seq 1 100); do
    # sqlite3.connect() in the CLI would create an empty, root-owned file
    # if called before the DynamicUser worker creates its database.
    if [[ -s /var/lib/opi-meshtastic-mail/mailbox.sqlite ]] && "$py" /opt/opi-mesh/meshtastic_mail.py inspect > "$proof/inspect" 2>/dev/null; then break; fi
    sleep 1
done
test -s /var/lib/opi-lxmf/address
grep -F 'Firmware: 2.7.26' "$proof/inspect"
for unit in opi-reticulum opi-lxmf opi-meshtastic-sim opi-meshtastic-mail; do systemctl is-active --quiet "$unit"; done
echo SOFTWARE-SERVICES-PASS
systemctl stop opi-lxmf opi-meshtastic-mail opi-reticulum opi-meshtastic-sim
armbian-config-zero2w --api module_sx1262_mode spi 500000 | grep -F '500000 Hz'
echo '# guest acceptance conffile sentinel' >> /etc/opi-mesh/reticulum.conf
"$py" guest_state.py seed
"$py" guest_state.py initial
feature_files > "$proof/baseline.files"
bash "$media/apply.sh" current
verify_version current
runtime_tools "$candidate"
"$py" guest_state.py upgraded
armbian-config-zero2w --api module_sx1262_mode diagnostics | grep -F '500000 Hz'
python3 guest_menu.py MESH01 'Choose a software node'
python3 guest_menu.py SXMD01 'Diagnostics'
finish_upgrade
