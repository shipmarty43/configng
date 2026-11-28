#!/bin/bash
# Populate the two simulated devices from the same composed board DTB.
set -euo pipefail
[[ $# == 4 ]] || { echo "Usage: $0 BOARD_DTB_DIR VENDOR_HEADERS ARM64_IMAGE EMPTY_WORKDIR" >&2; exit 2; }
dir=$(realpath "$1"); hdr=$(realpath "$2"); image=$(realpath "$3"); mkdir "$4"; w=$(realpath "$4")
src=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$src/../../.." && pwd)
q=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}; export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$w/boot/dtb" "$w/boot/overlay-user" "$w/root/dev" "$w/mod"
ln -s "$dir" "$w/boot/dtb/allwinner"
printf 'overlay_prefix=sun60i-a733\nfdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\nuser_overlays=client\n' > "$w/env"
printf '/dts-v1/;/plugin/;&spi2 {sensor@0 {reg=<0>;compatible="test,sensor";spi-max-frequency=<2000000>;};};' | dtc -q -@ -o "$w/boot/overlay-user/client.dtbo"
api() { python3 "$repo/share/armbian-config/a733_io.py" "$w/boot" "$w/env" "$@"; }
for selection in 'camera release' 'spi3-cs0 8000000 3' 'spi2 on' 'spi2-cs0 1000000 2'; do
    read -ra arg <<< "$selection"; api set "${arg[@]}" "$w/next"; mv "$w/next" "$w/env"
done
api compose-dtb "$w/board.dtb"
args=(-no-user-config -nodefaults -machine virt,gic-version=3 -smp 2 -cpu cortex-a55 -m 384M -display none -monitor none -serial none -nic none -no-reboot)
"$q" "${args[@]}" -machine "virt,dumpdtb=$w/virt.dtb"
for bus in 2 3; do
    parent=/qa-spi$bus
    if [[ $bus == 2 ]]; then client=/soc@3000000/spi@2542000/sensor@0; else client=/soc@3000000/spi@2543000/spidev@0; fi
    fdtput -c "$w/virt.dtb" "$parent"; fdtput -t s "$w/virt.dtb" "$parent" compatible test,opi-spi-double
    fdtput -t i "$w/virt.dtb" "$parent" qa,number "$bus"; fdtput -t i "$w/virt.dtb" "$parent" '#address-cells' 1
    fdtput -t i "$w/virt.dtb" "$parent" '#size-cells' 0; node="$parent/test@0"; fdtput -c "$w/virt.dtb" "$node"
    fdtput -t s "$w/virt.dtb" "$node" compatible rohm,dh2228fv
    for key in reg spi-max-frequency; do fdtput -t i "$w/virt.dtb" "$node" "$key" "$(fdtget -t u "$w/board.dtb" "$client" "$key")"; done
    for key in spi-cpol spi-cpha; do if fdtget "$w/board.dtb" "$client" "$key" >/dev/null 2>&1; then fdtput "$w/virt.dtb" "$node" "$key"; fi; done
done
cp "$src/qa_spi.c" "$w/mod"; echo 'obj-m += qa_spi.o' > "$w/mod/Makefile"
make -s -C "$hdr" M="$w/mod" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- modules
cp "$w/mod/qa_spi.ko" "$w/root"; aarch64-linux-gnu-gcc -Os -s -static -pthread "$src/init.c" -o "$w/root/init"
nonce=$(cat /proc/sys/kernel/random/uuid); echo "$nonce" > "$w/root/nonce"
(cd "$w/root" && find . -print0 | cpio --null -o -H newc 2>/dev/null | gzip -1 > "$w/init.gz")
trap 'rm -f "$w/ram"' EXIT
timeout --kill-after=5 90 "$q" "${args[@]}" -object "memory-backend-file,id=ram,size=384M,mem-path=$w/ram,share=on" -machine memory-backend=ram -dtb "$w/virt.dtb" -kernel "$image" -initrd "$w/init.gz" -append 'rdinit=/init panic=1' || :
LC_ALL=C grep -aFq "SPI-proof/$nonce/64/64/end" "$w/ram"
echo 'PASS 64 full-duplex exchanges per simultaneous client: SPI2 CS0 1 MHz mode 2, SPI3 CS0 8 MHz mode 3'
