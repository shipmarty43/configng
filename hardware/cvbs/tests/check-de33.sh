#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
if [ "$#" != 2 ]; then
	echo "usage: $0 /path/to/arm64-headers /path/to/patched-kernel-source" >&2
	exit 2
fi
headers=$(realpath "$1")
src=$(realpath "$2/drivers/gpu/drm/sun4i")
tests=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
prefix=${CROSS_COMPILE:-aarch64-linux-gnu-}
cp "$tests/check_de33.c" "$src/sun8i_csc.c" "$out/"
echo 'obj-y += sun8i_csc.o check_de33.o' > "$out/Kbuild"
make -C "$headers" ARCH=arm64 CROSS_COMPILE="$prefix" M="$out" W=1 \
	KCFLAGS="-I$src -ffunction-sections -fdata-sections -fno-stack-protector" \
	sun8i_csc.o check_de33.o
cat > "$out/run.c" <<'END'
#include <stdio.h>
#include <stdlib.h>
int check_de33(void);
/* No printk is expected on a valid conversion. */
void _printk(void) { abort(); }
int main(void)
{
	int ret = check_de33();
	if (ret)
		fprintf(stderr, "DE33 colour check failed in case %d\n", ret);
	else
		puts("PASS: 8 BT.601 bars on 6 channels, CVBS/HDMI/CVBS, black and blend control");
	return ret;
}
END
"${prefix}gcc" -O2 -static -Wl,--gc-sections "$out/run.c" "$out/check_de33.o" \
	"$out/sun8i_csc.o" -o "$out/check"
qemu-aarch64 "$out/check"
