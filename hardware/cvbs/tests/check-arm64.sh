#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Compile the real kernel objects and exercise the clock/reset paths in QEMU.
set -eu
if [ "$#" != 1 ]; then
	echo "usage: $0 /path/to/prepared-arm64-kernel-headers" >&2
	exit 2
fi
headers=$(realpath "$1")
src=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
prefix=${CROSS_COMPILE:-aarch64-linux-gnu-}
make -C "$headers" ARCH=arm64 CROSS_COMPILE="$prefix" M="$src" MO="$out" \
	W=1 KCFLAGS=-ffunction-sections h618-tve.o h618-tve-resources.o
# Discard device acquisition in this executable. The kernel objects above
# contain it; real platform/CCF/NVMEM provider registration requires Linux.
"${prefix}gcc" -O2 -Wall -Wextra -Werror -static -Wl,--gc-sections \
	-I"$src/tests/include" "$src/tests/power.c" "$out/h618-tve-resources.o" \
	-o "$out/power"
qemu-aarch64 "$out/power"
