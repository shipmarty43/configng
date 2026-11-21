#!/usr/bin/env bash
# Boot a disposable ARM64 kernel with only an initramfs and an in-memory gpiochip.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
k=$(realpath "${1:?prepared Armbian 6.18 ARM64 headers required}")
image=$(realpath "${2:?ARM64 Image required}")
busybox=$(realpath "${3:?static ARM64 BusyBox required}")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work"/{test,driver,root/bin,root/dev,root/proc,root/sys}
cp "$here"/{Makefile,header_gpio_double.c} "$work/test"
cp "$here"/../../../hardware/header-gpio/{Makefile,opi_header_gpio.c} "$work/driver"
for module in test driver; do
    make -s -j1 -C "$k" ARCH=arm64 CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" M="$work/$module" modules
    cp "$work/$module/"*.ko "$work/root/"
done
cp "$busybox" "$work/root/bin/busybox"
"${CROSS_COMPILE:-aarch64-linux-gnu-}gcc" -Wall -Wextra -Werror -O2 -static "$here/check_line.c" -o "$work/root/check_line"
install -m 755 "$here/init" "$work/root/init"
(cd "$work/root" && find . -print0 | cpio -o -0 -H newc --quiet | gzip -1 > "$work/root.gz")
qemu=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}
args=(-no-user-config -nodefaults -machine virt,gic-version=3 -accel tcg,thread=single,tb-size=16 -cpu cortex-a53 -smp 1 -m 256M -display none -nic none -monitor none -serial none -no-reboot)
"$qemu" "${args[@]}" -machine "virt,dumpdtb=$work/base.dtb"
dtc -q -@ -I dts -O dtb -o "$work/test.dtbo" "$here/double.dts"
fdtoverlay -i "$work/base.dtb" -o "$work/test.dtb" "$work/test.dtbo"
timeout 180 "$qemu" "${args[@]}" -chardev "file,id=log,path=$work/log" -device pci-serial,chardev=log \
    -dtb "$work/test.dtb" -kernel "$image" -initrd "$work/root.gz" -append 'console=ttyS0,115200 rdinit=/init panic=1'
grep -F 'PASS-GPIO-V2-CLAIM-AND-DEBOUNCE' "$work/log" || { tail -55 "$work/log"; exit 1; }
grep -F 'PASS-GPIO-PRESET-ARM64' "$work/log" || { tail -55 "$work/log"; exit 1; }
