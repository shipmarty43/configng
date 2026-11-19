#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build an external gzip initramfs, including the console node, without root.
set -eu
if [ "$#" != 6 ]; then
	echo "usage: $0 GEN_INIT_CPIO ARM64_BUSYBOX ARM64_MODETEST ARM64_LIBDIR INITRAMFS_GZ SCRATCH_DIR" >&2
	exit 2
fi
gen=$(realpath "$1")
busybox=$(realpath "$2")
modetest=$(realpath "$3")
lib=$(realpath "$4")
output=$(realpath -m "$5")
src=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
tmp=$(mktemp -d "$6/initramfs.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
# gen_init_cpio expands these variables after tokenizing each manifest entry.
export busybox modetest lib src
cat > "$tmp/list" <<'END'
dir /bin 0755 0 0
dir /dev 0755 0 0
dir /lib 0755 0 0
dir /proc 0555 0 0
dir /sys 0555 0 0
dir /tmp 01777 0 0
nod /dev/console 0600 0 0 c 5 1
file /bin/busybox ${busybox} 0755 0 0
slink /bin/sh busybox 0777 0 0
file /bin/modetest ${modetest} 0755 0 0
file /lib/ld-linux-aarch64.so.1 ${lib}/ld-linux-aarch64.so.1 0755 0 0
file /lib/libdrm.so.2 ${lib}/libdrm.so.2 0755 0 0
file /lib/libc.so.6 ${lib}/libc.so.6 0755 0 0
file /bin/cvbs-bars ${src}/cvbs-bars 0755 0 0
file /init ${src}/init 0755 0 0
END
"$gen" -t 0 "$tmp/list" > "$tmp/root.cpio"
gzip -n -c "$tmp/root.cpio" > "$tmp/initramfs.gz"
mv "$tmp/initramfs.gz" "$output"
