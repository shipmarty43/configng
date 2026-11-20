#!/usr/bin/env bash
# Isolated QEMU virt boot of a regular Armbian Zero 2W image. No mount, host
# block device, network, directory export or physical peripheral is passed in.
set -euo pipefail
if (( $# < 4 || $# > 5 )); then
    echo "Usage: $0 CLEAN.img RELEASE_DIR ARM64_BUSYBOX NEW_DISK_WORKDIR [lifecycle|fresh-current]" >&2
    exit 2
fi
base=$(realpath "$1")
release=$(realpath "$2")
busy=$(realpath "$3")
scenario=${5:-lifecycle}
case "$scenario" in
    lifecycle) boots=(first reboot) ;;
    fresh-current) boots=(fresh) ;;
    *) echo "Unknown test scenario: $scenario" >&2; exit 2 ;;
esac
[[ -f "$base" && -f "$busy" ]] || { echo "Regular image files required" >&2; exit 2; }
mkdir -m 700 "$4"
work=$(realpath "$4")
tests=$(cd -- "$(dirname -- "$0")" && pwd)
qemu=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}
dtc=${DTC:-dtc}
merge=${FDTOVERLAY:-fdtoverlay}
offset=$(sfdisk --json "$base" | python3 -c 'import json,sys; t=json.load(sys.stdin)["partitiontable"]; assert t["unit"]=="sectors" and len(t["partitions"])==1; print(t["sectorsize"]*t["partitions"][0]["start"])')
kernel=$(debugfs -R 'ls -p /boot' "$base?offset=$offset" 2>/dev/null | awk -F/ '$3=="100644" && $6 ~ /^vmlinuz-/{print $6;exit}')
test -n "$kernel"
debugfs -R "dump /boot/$kernel $work/Image" "$base?offset=$offset"
test -s "$work/Image"
qemu-img create -q -f qcow2 -F raw -b "$base" "$work/root.qcow2"
mkdir -p "$work/payload"/{previous,current,ubuntu}
cp "$release"/previous/*.deb "$work/payload/previous/"
cp "$release"/current/*.deb "$work/payload/current/"
cp "$release"/ubuntu/*.deb "$work/payload/ubuntu/"
cp "$tests"/{guest-test.sh,guest_menu.py,guest_state.py} "$work/payload/"
cp "$release"/{SHA256SUMS,apply.sh} "$work/payload/"
(cd "$work/payload" && sha256sum --quiet --strict -c SHA256SUMS)
if [[ $scenario == fresh-current ]]; then touch "$work/payload/fresh-current"; fi
cat > "$work/payload/drive.sh" <<'GUEST'
#!/bin/sh
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if /bin/bash /mnt/opi-release/guest-test.sh; then echo OPI-VM-PHASE-PASS
else echo OPI-VM-PHASE-FAILED; fi
sync
systemctl poweroff --no-block
GUEST
size=$(du -sm "$work/payload" | cut -f1)
truncate -s "$((size+18))M" "$work/input.ext4"
mke2fs -q -F -t ext4 -m0 -L OPI-PKGS -d "$work/payload" "$work/input.ext4"
mkdir -p "$work/early"/{bin,dev,proc,sys,newroot}
cp "$busy" "$work/early/bin/busybox"
cat > "$work/early/init" <<'EARLY'
#!/bin/busybox sh
set -eu
export PATH=/bin
/bin/busybox --install -s /bin
mount -t devtmpfs dev /dev; mount -t proc proc /proc; mount -t sysfs sys /sys
for i in $(seq 1 30); do if test -b /dev/sda1 && test -b /dev/sdb; then break; fi; sleep 1; done
mount -t ext4 /dev/sda1 /newroot
r=/newroot
mkdir -p "$r/run" "$r/mnt/opi-release"
mount -t tmpfs -o mode=755,nosuid,nodev tmpfs "$r/run"
mount -t ext4 -o ro,noload /dev/sdb "$r/mnt/opi-release"
test -f "$r/mnt/opi-release/guest-test.sh"
mkdir -p "$r/run/systemd/system"
cat > "$r/run/systemd/system/opi-package.target" <<'UNIT'
[Unit]
Description=Isolated package acceptance
Requires=basic.target opi-package-test.service
After=basic.target
AllowIsolate=yes
UNIT
cat > "$r/run/systemd/system/opi-package-test.service" <<'UNIT'
[Unit]
Description=Run package lifecycle checks on virtual media
After=basic.target
[Service]
Type=oneshot
ExecStart=/bin/sh /mnt/opi-release/drive.sh
TimeoutStartSec=40min
StandardOutput=tty
StandardError=inherit
TTYPath=/dev/ttyS0
UNIT
for fs in dev proc sys; do mount -o move "/$fs" "$r/$fs"; done
exec switch_root /newroot /sbin/init
EARLY
chmod 755 "$work/early/init"
(cd "$work/early" && find . -print0 | cpio --null -o -H newc 2>/dev/null | gzip -1 > "$work/init.gz")
vm=(-no-user-config -nodefaults -machine virt,gic-version=3 -accel tcg,thread=single,tb-size=32
    -cpu cortex-a53 -smp 1 -m 640M -display none -monitor none -nic none -no-reboot -serial none)
"$qemu" "${vm[@]}" -machine "virt,dumpdtb=$work/virt.dtb"
cat > "$work/metadata.dts" <<'DT'
/dts-v1/;
/plugin/;
/ {
 fragment@0 { target-path = "/"; __overlay__ {
   compatible = "linux,dummy-virt", "xunlong,orangepi-zero2w", "allwinner,sun50i-h618";
   soc { #address-cells=<2>; #size-cells=<2>; status="disabled";
     spi@5011000 { reg=<0 0x5011000 0 0x1000>; #address-cells=<1>; #size-cells=<0>; status="disabled";
       radio@0 { reg=<0>; compatible="semtech,sx1262"; spi-max-frequency=<2000000>; status="disabled"; };
     };
   };
 }; };
};
DT
"$dtc" -q -@ -O dtb -I dts -o "$work/meta.dtbo" "$work/metadata.dts"
"$merge" -i "$work/virt.dtb" -o "$work/guest.dtb" "$work/meta.dtbo"
for boot in "${boots[@]}"; do
 log="$work/$boot.log"
 timeout --kill-after=30s 45m "$qemu" "${vm[@]}" -chardev "file,id=c,path=$log" -device pci-serial,chardev=c \
    -device qemu-xhci,id=hc -drive "if=none,id=root,file=$work/root.qcow2,format=qcow2,cache=none" \
    -device usb-storage,bus=hc.0,drive=root -drive "if=none,id=input,file=$work/input.ext4,format=raw,readonly=on,cache=none" \
    -device usb-storage,bus=hc.0,drive=input -dtb "$work/guest.dtb" -kernel "$work/Image" -initrd "$work/init.gz" \
    -append 'console=ttyS0,115200 rdinit=/init panic=5 systemd.unit=opi-package.target systemd.gpt_auto=0 fstab=no systemd.mask=timers.target systemd.mask=armbian-zram-config.service systemd.mask=armbian-ramlog.service systemd.mask=systemd-zram-setup@zram0.service'
 if ! grep -aq '^OPI-VM-PHASE-PASS' "$log"; then grep -aE 'GUEST-ERROR|PHASE-FAILED|Traceback|Error:|^E:|Failed to start|error while loading' "$log" | tail -20 || :; exit 1; fi
 grep -aE '^(GUEST |CLEAN-|DPKG-PASS|STATE-PASS|IMPORT-PASS|TUI-PASS|SOFTWARE-SERVICES-PASS|PASS-|OPI-VM-PHASE-PASS)' "$log"
done
if [[ $scenario == lifecycle ]]; then
    grep -aq '^PASS-INSTALL-UPGRADE-DOWNGRADE' "$work/first.log"
    grep -aq '^PASS-REBOOT' "$work/reboot.log"
else
    grep -aq '^PASS-FRESH-CURRENT' "$work/fresh.log"
fi
du -h "$work/root.qcow2"
