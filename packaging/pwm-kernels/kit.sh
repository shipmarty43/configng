#!/bin/bash
# Entry point installed beside current/, rollback/ and support/.
set -euo pipefail
cd "$(dirname "$0")"
sha256sum --quiet -c SHA256SUMS
. /etc/armbian-image-release
read -r board imagepkg abi original updated < board.txt
[[ $BOARD == "$board" && $(dpkg --print-architecture) == arm64 ]] || { echo 'Kit and board do not match.' >&2; exit 1; }
installed=$(dpkg-query -W -f='${Version}' "$imagepkg")
[[ $installed == "$original" || $installed == "$updated" ]] || { echo "Unsupported installed kernel package: $installed" >&2; exit 1; }
case ${1:-} in
  install) dpkg -i ./current/*.deb ./support/*.deb ;;
  rollback-kernel) dpkg -i ./rollback/*.deb ;;
  *) echo "Usage: $0 install|rollback-kernel" >&2; exit 2 ;;
esac
