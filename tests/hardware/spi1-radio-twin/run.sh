#!/bin/bash
# Only regular images, private boot files and QEMU memory. No host peripherals.
set -euo pipefail
[[ $# == 6 ]] || { echo "Usage: $0 ARM64_IMAGE KERNEL_HEADERS BOARD_DTB_DIR SX_PYTHON_INITRAMFS GUI_CHECKOUT NEW_WORKDIR" >&2; exit 2; }
kernel=$(realpath "$1"); headers=$(realpath "$2"); dt=$(realpath "$3"); initrd=$(realpath "$4"); gui=$(realpath "$5")
[[ -f $kernel && -f $initrd ]]; mkdir "$6"; w=$(realpath "$6")
src=$(cd "$(dirname "$0")" && pwd); cfg=$(cd "$src/../../.." && pwd); q=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}
export PYTHONDONTWRITEBYTECODE=1; script_dir="$cfg/bin"; declare -A module_options
for m in devicetree_overlays sx1262_overlay ups_dfr0528 spi_clocks; do source "$cfg/tools/modules/system/module_$m.sh"; done
mkdir -p "$w/b/dtb" "$w/b/overlay-user" "$w/live" "$w/mod" "$w/extra/triple/core"; ln -s "$dt" "$w/b/dtb/allwinner"
_ups_dfr_boot() { echo "$w/b"; }; _ups_dfr_dt() { echo "$w/live"; }
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$w/live/compatible"
printf '%s\n' 'armbianEnv.txt overlay-user/${overlay_file}.dtbo' > "$w/b/boot.scr"
printf 'overlay_prefix=sun50i-h616\n' > "$w/b/armbianEnv.txt"
module_sx1262_overlay shared
module_spi_clocks set spi1 1 1000000
module_spi_clocks set spi1 2 4000000
_zero2w_overlay_prepare compose "$w/b/armbianEnv.txt" "$w/board.dtb" sx1262 ''
# Apply the same three installed blobs to the equivalent in-memory providers.
args=(-no-user-config -nodefaults -machine virt,gic-version=3 -cpu cortex-a55 -smp 2 -m 512M -display none -monitor none -serial none -nic none -no-reboot)
"$q" "${args[@]}" -machine "virt,dumpdtb=$w/virt.dtb"
dtc -q -@ -I dts -O dtb -o "$w/providers.dtbo" "$src/virt.dts"
names=$(sed -n 's/^user_overlays=//p' "$w/b/armbianEnv.txt"); read -ra names <<< "$names"
blobs=(); for n in "${names[@]}"; do blobs+=("$w/b/overlay-user/$n.dtbo"); done
fdtoverlay -i "$w/virt.dtb" -o "$w/guest.dtb" "$w/providers.dtbo" "${blobs[@]}"
cp "$src/qa_spi1.c" "$w/mod"; echo 'obj-m += qa_spi1.o' > "$w/mod/Makefile"
make -s -C "$headers" M="$w/mod" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- modules
cp "$w/mod/qa_spi1.ko" "$src/exchange.py" "$w/extra/triple/"
cp "$gui"/core/{hardware_config,header_peripherals,radio_lock,spi_clock,sx1262_spi}.py "$w/extra/triple/core/"
touch "$w/extra/triple/core/__init__.py"
python3 -c 'import json,sys,yaml;json.dump(yaml.safe_load(open(sys.argv[1])),sys.stdout)' "$gui/config/opi-zero2w-spi1-radios.yaml" > "$w/extra/triple/profile.json"
cp "$gui/hardware/overlays/"{opi-radio,opi-spi1-peers}.conf "$w/extra/triple/"
cat > "$w/extra/triple/init" <<'GUEST'
#!/bin/busybox sh
set -eu
export PATH=/bin:/usr/bin PYTHONDONTWRITEBYTECODE=1
/bin/busybox --install -s /bin
mount -t devtmpfs dev /dev; mount -t proc proc /proc; mount -t sysfs sys /sys
trap 'sync; poweroff -f' EXIT
mkdir -p /run/lock
cat /triple/*.conf | while read -r type path mode rest; do test "$type" = f; touch "$path"; chmod "$mode" "$path"; done
insmod /triple/qa_spi1.ko
/usr/bin/python3 -I /triple/exchange.py
echo PASS-SPI1-RADIOS
GUEST
chmod +x "$w/extra/triple/init"
cat "$initrd" > "$w/test.gz"; (cd "$w/extra" && find . -print0 | cpio --null -o -H newc 2>/dev/null | gzip -1 >> "$w/test.gz")
timeout --kill-after=5 160 "$q" "${args[@]}" -dtb "$w/guest.dtb" -kernel "$kernel" -initrd "$w/test.gz" \
    -chardev "file,id=c,path=$w/console" -device pci-serial,chardev=c -append 'console=ttyS0,115200 rdinit=/triple/init fw_devlink=off panic=2' || :
grep -a '^PASS' "$w/console" || :
grep -aq '^PASS-SPI1-RADIOS' "$w/console"
