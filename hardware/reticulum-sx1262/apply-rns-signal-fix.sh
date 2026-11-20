#!/usr/bin/env bash
# Apply or reverse the host decoder correction in this project's pinned virtualenv.
set -euo pipefail
patchfile=$(cd -- "$(dirname -- "$0")" && pwd)/rns-1.6.1-signal-escape.patch
python=/opt/opi-mesh/venv/bin/python
site=$("$python" -c 'import importlib.metadata as m, sysconfig
if m.version("rns") != "1.6.1": raise SystemExit("Expected RNS 1.6.1")
print(sysconfig.get_path("purelib"))')
file="$site/RNS/Interfaces/RNodeInterface.py"
original=ca012e16ee6070464bf54dc5c03f3b49b1e65fc7ff7ec9890caba475a8a5c09d
fixed=1024690fe61c532ce6ac25c9afec2397850355d32bb83caef72441458d0afef9
before=$original; after=$fixed; options=(--forward)
case "${1:-apply}" in
    apply) ;;
    revert) before=$fixed; after=$original; options=(--reverse) ;;
    *) echo 'Expected apply or revert' >&2; exit 2 ;;
esac
actual=$(sha256sum "$file"); actual=${actual%% *}
if [[ "$actual" == "$after" ]]; then echo 'RNS signal decoder already matches'; exit 0; fi
if [[ "$actual" != "$before" ]]; then echo 'Unexpected RNS decoder checksum' >&2; exit 1; fi
tmp=$(mktemp --tmpdir="$(dirname "$file")" .rnode-signal.XXXXXXXX)
trap 'rm -f -- "$tmp"' EXIT
patch --batch --fuzz=0 "${options[@]}" -o "$tmp" "$file" "$patchfile"
printf '%s  %s\n' "$after" "$tmp" | sha256sum -c -
chmod --reference="$file" "$tmp"
mv -T "$tmp" "$file"
