#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
if [ "$#" != 2 ]; then
	echo "usage: $0 Image initramfs.cpio.gz" >&2
	exit 2
fi
log=$(mktemp)
trap 'rm -f "$log"' EXIT
# virt supplies its own DT and PL011 console. Debugfs state is checked in /init.
if ! timeout 60s "${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}" \
	-machine virt -accel tcg -cpu cortex-a53 -smp 1 -m 256M \
	-display none -serial stdio -monitor none -nic none -no-reboot \
	-kernel "$1" -initrd "$2" -append 'console=ttyAMA0 rdinit=/init cvbs.smoke=1' > "$log" 2>&1; then
	cat "$log"
	exit 1
fi
cat "$log"
grep -q '^PASS virtual KMS modeset and disable' "$log"
