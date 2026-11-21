#!/usr/bin/env bash
# Package a tested ARM64 .ko for its exact Armbian kernel release.
set -euo pipefail
[[ $# == 2 ]] || { echo "Usage: $0 opi_header_gpio.ko OUTPUT_DIR" >&2; exit 2; }
ko=$(realpath "$1")
abi=$(modinfo -F vermagic "$ko"); abi=${abi%% *}
[[ $abi =~ ^[0-9][a-z0-9.+-]+$ && $(modinfo -F name "$ko") == opi_header_gpio ]]
LC_ALL=C readelf -h "$ko" | grep -q 'Machine:.*AArch64'
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
name="opi-header-gpio-modules-$abi"
install -Dm644 "$ko" "$work/usr/lib/modules/$abi/updates/opi-header-gpio/opi_header_gpio.ko"
mkdir -p "$work/DEBIAN" "$2"
cat > "$work/DEBIAN/control" <<CONTROL
Package: $name
Version: 1.0-1
Architecture: arm64
Depends: kmod
Maintainer: Armbian configurator maintainers <shipmarty43@users.noreply.github.com>
Description: One-shot header GPIO electrical presets for Linux $abi
CONTROL
for script in postinst postrm; do
    cat > "$work/DEBIAN/$script" <<SCRIPT
#!/bin/sh
set -e
if [ -f /lib/modules/$abi/modules.order ]; then depmod -a $abi; fi
SCRIPT
    chmod 755 "$work/DEBIAN/$script"
done
dpkg-deb --root-owner-group --threads-max=1 --build "$work" "$2/${name}_1.0-1_arm64.deb"
