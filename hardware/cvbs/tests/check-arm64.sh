#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Compile the real kernel objects and exercise the clock/reset paths in QEMU.
set -eu
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
	echo "usage: $0 /path/to/prepared-arm64-kernel-headers [/path/to/linux-source]" >&2
	exit 2
fi
headers=$(realpath "$1")
src=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
prefix=${CROSS_COMPILE:-aarch64-linux-gnu-}
make -C "$headers" ARCH=arm64 CROSS_COMPILE="$prefix" M="$src" MO="$out" \
	W=1 KCFLAGS=-ffunction-sections h618-tve.o h618-tve-resources.o h618-drm.o
# Discard device acquisition in this executable. The kernel objects above
# contain it; real platform/CCF/NVMEM provider registration requires Linux.
"${prefix}gcc" -O2 -Wall -Wextra -Werror -static -Wl,--gc-sections \
	-I"$src/tests/include" "$src/tests/power.c" "$out/h618-tve-resources.o" \
	-o "$out/power"
qemu-aarch64 "$out/power"

if [ "$#" -eq 2 ]; then
	drm_src=$(realpath "$2/drivers/gpu/drm")
	mkdir "$out/kms"
	cp "$drm_src/drm_modes.c" "$src/tests/check_modes.c" "$out/kms/"
	echo 'obj-y += drm_modes.o check_modes.o' > "$out/kms/Kbuild"
	make -C "$headers" ARCH=arm64 CROSS_COMPILE="$prefix" M="$out/kms" W=1 \
		KCFLAGS="-ffunction-sections -fdata-sections -fno-stack-protector -I$drm_src -I$src" \
		drm_modes.o check_modes.o
	"${prefix}gcc" -O2 -static -Wl,--gc-sections "$src/tests/run_modes.c" \
		"$out/kms/check_modes.o" "$out/kms/drm_modes.o" -o "$out/kms/test"
	qemu-aarch64 "$out/kms/test"
fi
