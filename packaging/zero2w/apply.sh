#!/usr/bin/env bash
# Offline package installation for an Armbian Resolute ARM64 image.
set -euo pipefail
case "${1:-}" in
    current) downgrade=() ;;
    previous) downgrade=(--allow-downgrades) ;;
    *) echo "Usage: $0 current|previous" >&2; exit 2 ;;
esac
(( $# == 1 && EUID == 0 )) || { echo "Run as root with one release name" >&2; exit 2; }
test "$(dpkg --print-architecture)" = arm64
. /etc/os-release
test "${VERSION_CODENAME:-}" = resolute
test -r /etc/armbian-release
cd -- "$(dirname -- "$(realpath "$0")")"
sha256sum --quiet --strict -c SHA256SUMS
files=()
while read -r digest file; do
    case "$file" in
        "$1"/*.deb) files+=("$PWD/$file") ;;
        drivers/*.deb)
            if [[ $1 == current && $(dpkg-deb -f "$file" Package) == "opi-header-gpio-modules-$(uname -r)" ]]; then
                files+=("$PWD/$file")
            fi ;;
        ubuntu/*.deb)
            name=$(dpkg-deb -f "$file" Package)
            status=$(dpkg-query -W -f='${db:Status-Status}' "$name" 2>/dev/null || :)
            if [[ $status != installed ]]; then files+=("$PWD/$file"); fi ;;
    esac
done < SHA256SUMS
# Empty sources and lists let APT stage the explicitly supplied local files.
# --no-download also disables staging those local files on Resolute's APT.
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
chmod 755 "$scratch"
mkdir "$scratch/sources" "$scratch/lists"
touch "$scratch/sources.list"
# Armbian's dpkg post-invoke hook runs its own apt-get to refresh the MOTD.
# Give nested APT processes the same offline view as the installer.
cat > "$scratch/apt.conf" <<CONF
Dir::Etc::sourcelist "$scratch/sources.list";
Dir::Etc::sourceparts "$scratch/sources";
Dir::State::lists "$scratch/lists";
Dir::Cache::pkgcache "";
Dir::Cache::srcpkgcache "";
CONF
APT_CONFIG="$scratch/apt.conf" apt-get -y --no-remove --no-install-recommends "${downgrade[@]}" \
    -o Dpkg::Use-Pty=0 install "${files[@]}"
