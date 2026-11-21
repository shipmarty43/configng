#!/usr/bin/env bash
set -euo pipefail
if (( $# != 3 )); then echo "Usage: $0 GPIO_SIM_KERNEL_OBJECTS ARM64_PYTHON_INITRAMFS.gz NEW_WORK_DIR" >&2; exit 2; fi
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
mkdir -m 700 "$3"
w=$(realpath "$3")
python3 "$here/build-kernel.py" "$1" "$w"
mkdir -p "$w/extra/lab"
cp "$here"/{init,check.py} "$w/extra/lab/"
cp "$repo"/share/armbian-config/{h616_pwm,h616_uart,h616_settings,console_tty}.py "$w/extra/lab/"
chmod +x "$w/extra/lab/init"
(cd "$w/extra" && find . -print0 | cpio --quiet --null -o -H newc | gzip -1 > "$w/extra.gz")
cat "$2" "$w/extra.gz" > "$w/initrd.gz"
dtc -q -@ -I dts -O dtb -o "$w/buses.dtbo" "$here/buses.dts"
dtc -q -@ -I dts -O dtb -o "$w/ups.dtbo" "$repo/hardware/dfrobot-ups/zero2w-dfr0528.dts"
qemu=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}
vm=(-no-user-config -nodefaults -M virt -accel tcg,thread=single -smp 1 -cpu cortex-a53 -m 256M -display none -monitor none -nic none -no-reboot)
"$qemu" "${vm[@]}" -machine "virt,dumpdtb=$w/virt.dtb"
for hz in 100000 400000; do
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$repo/share/armbian-config" python3 - "$w" "$hz" <<'PY'
from pathlib import Path
import sys
from dt_clock_overlay import install_overlay
from i2c_clocks import BUSES
install_overlay(Path(sys.argv[1]), sys.argv[2], BUSES["twi1"], {"clock-frequency": int(sys.argv[2])})
PY
    fdtoverlay -i "$w/virt.dtb" -o "$w/guest.dtb" "$w/buses.dtbo" "$w/ups.dtbo" "$w/$hz.dtbo"
    timeout 100 "$qemu" "${vm[@]}" -kernel "$w/Image" -initrd "$w/initrd.gz" -dtb "$w/guest.dtb" \
        -serial stdio -append 'console=ttyAMA0 rdinit=/lab/init panic=2' > "$w/$hz.log" 2>&1
    grep -a '^PASS' "$w/$hz.log"
    grep -aq '^PASS-H616-IO-TWIN' "$w/$hz.log"
done
