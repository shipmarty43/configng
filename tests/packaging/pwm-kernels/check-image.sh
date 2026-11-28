#!/bin/bash
# The only writable guest devices are scratch files under a new work directory.
set -euo pipefail
if (( $# < 6 || $# > 7 )); then
    echo "Usage: $0 BOARD CLEAN.img ROLLBACK.deb CANDIDATE.deb|before BUSYBOX NEW_WORKDIR [QA-ECAM.ko]" >&2; exit 2
fi
board=$1; clean=$(realpath "$2"); stock=$(realpath "$3"); candidate=$4; busy=$(realpath "$5")
for file in "$clean" "$stock" "$busy"; do [[ -f $file ]] || exit 2; done
mkdir -m 700 "$6"; w=$(realpath "$6"); here=$(cd "$(dirname "$0")" && pwd)
q=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}
pkg=$(dpkg-deb -f "$stock" Package); orig=$(dpkg-deb -f "$stock" Version)
rel=$(dpkg-deb -f "$stock" Armbian-Kernel-Version-Family)
mkdir -p "$w/input" "$w/early"/{bin,dev,proc,sys,newroot}
extract_image() { dpkg-deb --fsys-tarfile "$1" | tar -xO "./boot/vmlinuz-$rel" > "$2"; }
extract_image "$stock" "$w/stock.Image"; stocksha=$(sha256sum "$w/stock.Image" | cut -d' ' -f1)
cp "$here/guest.sh" "$here/ramdisk.py" "$w/input/"
phases=(before); new=unused; expected=unused
if [[ $candidate != before ]]; then
    [[ -f $candidate && $(dpkg-deb -f "$candidate" Package) == "$pkg" ]]
    new=$(dpkg-deb -f "$candidate" Version); dpkg --compare-versions "$new" gt "$orig"
    extract_image "$candidate" "$w/from-package.Image"
    expected=$(sha256sum "$w/from-package.Image" | cut -d' ' -f1); [[ $expected != "$stocksha" ]]
    cp "$candidate" "$w/input/current.deb"; cp "$stock" "$w/input/stock.deb"
    phases=(install downgrade restored)
fi
echo "$board $pkg $rel $orig $new $stocksha $expected" > "$w/input/manifest"
dt_args=()
if [[ -n ${PWM_CONFIG_KIT:-} ]]; then
    [[ $candidate != before ]]
    kit=$(realpath "$PWM_CONFIG_KIT")
    (cd "$kit" && sha256sum --quiet -c SHA256SUMS)
    cmp "$w/input/current.deb" "$kit"/current/*.deb
    cmp "$w/input/stock.deb" "$kit"/rollback/*.deb
    cp -a "$kit" "$w/input/kit"
    rm "$w/input/current.deb" "$w/input/stock.deb"
    cp "$here/../header-kit/"{menu.py,profile.sh} "$w/input/"
    case "$board" in
        orangepizero2w) chip=allwinner,sun50i-h618 ;;
        orangepizero3w) chip=arm,sun60iw2p1 ;;
        *) exit 2 ;;
    esac
    # Supply the board identity for the real menu guard, with QEMU peripherals only.
    "$q" -machine "virt,gic-version=3,dumpdtb=$w/virt.dtb" -cpu cortex-a55 -smp 2 -m 896M -nic none -nodefaults -display none
    fdtput -t s "$w/virt.dtb" / compatible linux,dummy-virt "xunlong,$(echo "$board" | sed s/orangepizero/orangepi-zero/)" "$chip"
    if [[ -n ${PWM_QA_I2C:-} ]]; then
        cp "$PWM_QA_I2C" "$w/input/qa_i2c.ko"
        if [[ $board == orangepizero2w ]]; then parent=/soc; child=i2c@5002400; else parent=/soc@3000000; child=twi@2510000; fi
        fdtget -p "$w/virt.dtb" "$parent" >/dev/null 2>&1 || fdtput -c "$w/virt.dtb" "$parent"; fdtput -c "$w/virt.dtb" "$parent/$child"
        fdtput -t s "$w/virt.dtb" "$parent/$child" status disabled
    fi
    if [[ -n ${PWM_QA_GPIO:-} ]]; then
        [[ $board == orangepizero3w ]]
        cp "$PWM_QA_GPIO" "$w/input/qa_gpio.ko"
        fdtget -p "$w/virt.dtb" /soc@3000000 >/dev/null 2>&1 || fdtput -c "$w/virt.dtb" /soc@3000000
        for node in pinctrl@2000000 pinctrl@7025000; do
            addr=/soc@3000000/$node
            fdtput -c "$w/virt.dtb" "$addr"
            fdtput -t s "$w/virt.dtb" "$addr" status disabled
            fdtput -t i "$w/virt.dtb" "$addr" '#gpio-cells' 3
            fdtput "$w/virt.dtb" "$addr" gpio-controller
        done
    fi
    dt_args=(-dtb "$w/virt.dtb")
fi
cp "$here/init" "$w/early/init"; chmod 755 "$w/early/init"
cp "$busy" "$w/early/bin/busybox"
if [[ $# == 7 ]]; then test -f "$7"; cp "$7" "$w/early/qa-ecam.ko"; fi
(cd "$w/early" && find . -print0 | cpio --null -o -H newc 2>/dev/null | gzip -1 > "$w/init.gz")
qemu-img create -q -f qcow2 -F raw -b "$clean" "$w/root.qcow2"
truncate -s "$(( $(du -sm --apparent-size --count-links "$w/input" | cut -f1) + 32 ))M" "$w/input.ext4"
mke2fs -q -F -t ext4 -m0 -L PWM_INPUT -d "$w/input" "$w/input.ext4"
truncate -s 128M "$w/result.ext4"; mke2fs -q -F -t ext4 -m0 -L PWM_RESULT "$w/result.ext4"
kernel="$w/stock.Image"
for phase in "${phases[@]}"; do
    timeout --kill-after=15s "${PWM_VM_TIMEOUT:-35m}" "$q" -no-user-config -nodefaults -machine virt,gic-version=3 \
        -accel tcg,thread=multi,tb-size=48 -cpu cortex-a55 -smp 2 -m 896M -nic none -display none -monitor none -no-reboot \
        -serial none -chardev "file,id=c,path=$w/$phase.serial" -device pci-serial,chardev=c \
        -device qemu-xhci,id=hc \
        -drive "if=none,id=root,file=$w/root.qcow2,format=qcow2,cache=none" -device usb-storage,bus=hc.0,drive=root \
        -drive "if=none,id=input,file=$w/input.ext4,format=raw,readonly=on" -device usb-storage,bus=hc.0,drive=input \
        -drive "if=none,id=result,file=$w/result.ext4,format=raw,cache=none" -device usb-storage,bus=hc.0,drive=result \
        "${dt_args[@]}" -kernel "$kernel" -initrd "$w/init.gz" -append "console=ttyS0,115200 rdinit=/init panic=2 qa_phase=$phase systemd.unit=pwm-qa.target fstab=no systemd.gpt_auto=0 systemd.mask=timers.target systemd.mask=armbian-zram-config.service systemd.mask=armbian-ramlog.service systemd.mask=systemd-zram-setup@zram0.service" || :
    debugfs -R "dump /$phase.log $w/$phase.log" "$w/result.ext4" 2>/dev/null
    [[ -s $w/$phase.log ]] && tail -8 "$w/$phase.log"
    [[ $(debugfs -R "cat /$phase.pass" "$w/result.ext4" 2>/dev/null) == PASS ]] || exit 1
    case "$phase" in
        install) next=installed; hash=$expected ;;
        downgrade) next=restored; hash=$stocksha ;;
        *) continue ;;
    esac
    kernel="$w/$next.Image"
    debugfs -R "dump /$next.Image $kernel" "$w/result.ext4"
    echo "$hash  $kernel" | sha256sum -c -
done
