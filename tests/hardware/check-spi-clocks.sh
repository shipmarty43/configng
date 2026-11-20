#!/usr/bin/env bash
# Real Zero 2W DTB, two synthetic header clients, boot files in a private directory.
set -euo pipefail
[[ $# == 1 && -f $1 ]] || { echo "Usage: $0 sun50i-h618-orangepi-zero2w.dtb" >&2; exit 2; }
root=$(cd "$(dirname "$0")/../.." && pwd)
script_dir="$root/bin"
declare -A module_options
for module in devicetree_overlays ups_dfr0528 sx1262_overlay spi_clocks; do
    source "$root/tools/modules/system/module_$module.sh"
done
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
bootroot="$workdir/boot"
mkdir -p "$bootroot/dtb/allwinner/overlay" "$bootroot/overlay-user" "$workdir/live"
cp "$1" "$bootroot/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb"
_ups_dfr_boot() { echo "$bootroot"; }
_ups_dfr_dt() { echo "$workdir/live"; }
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$workdir/live/compatible"
printf 'armbianEnv.txt\noverlay-user/${overlay_file}.dtbo\n' > "$bootroot/boot.scr"
conf="$bootroot/armbianEnv.txt"
printf 'overlay_prefix=sun50i-h616\nrootdev=unchanged\n' > "$conf"
api() { module_spi_clocks "$@"; }
reject() { if "$@"; then echo "Unexpected success: $*" >&2; exit 1; fi; }
[[ $(api list spi0) == $'0\tjedec,spi-nor' && -z $(api list spi1) ]]
cat > "$workdir/spi.dts" <<'DT'
/dts-v1/; /plugin/;
&spi1 {
    status = "okay"; #address-cells=<1>; #size-cells=<0>; num-cs=<2>;
    spidev@0 { compatible="rohm,dh2228fv"; reg=<0>; spi-max-frequency=<40000000>; };
    nfc@1 { compatible="nxp,pn532"; reg=<1>; spi-max-frequency=<10000000>; };
};
DT
dtc -q -I dts -O dtb -@ -o "$bootroot/dtb/allwinner/overlay/sun50i-h616-test.dtbo" "$workdir/spi.dts"
echo 'overlays=test' >> "$conf"
cp "$conf" "$workdir/original"
[[ $(api list spi1) == $'0\trohm,dh2228fv\n1\tnxp,pn532' ]]
api set spi0 0 18000000
api set spi1 0 2000000 & first=$!
api set spi1 1 5000000 & second=$!
wait "$first"; wait "$second"
cp "$conf" "$workdir/saved"
api set spi1 1 5000000
api set spi0 0 18000000
cmp "$conf" "$workdir/saved"
compose() { _zero2w_overlay_prepare compose "$conf" "$workdir/current.dtb" spi-clocks ''; }
check_rates() {
    compose
    [[ $(fdtget -t u "$workdir/current.dtb" /soc/spi@5010000/flash@0 spi-max-frequency) == "$1" ]]
    [[ $(fdtget -t u "$workdir/current.dtb" /soc/spi@5011000/spidev@0 spi-max-frequency) == "$2" ]]
    [[ $(fdtget -t u "$workdir/current.dtb" /soc/spi@5011000/nfc@1 spi-max-frequency) == "$3" ]]
}
check_rates 18000000 2000000 5000000
# A different chip at the same CS may retain exactly the same DT node path.
sed 's/nxp,pn532/ti,cc1101/' "$workdir/spi.dts" > "$workdir/swapped.dts"
dtc -q -@ -I dts -O dtb -o "$bootroot/dtb/allwinner/overlay/sun50i-h616-swapped.dtbo" "$workdir/swapped.dts"
reject _dt_overlays_write_config "$conf" false swapped
# A changed managed blob must not introduce extra properties into another boot.
active_flash=$(awk '/^user_overlays=/{sub(/^user_overlays=/,""); for(i=1;i<=NF;i++) if($i~/^opi-sclk-spi0-cs0-/) print $i}' "$conf")
blob="$bootroot/overlay-user/$active_flash.dtbo"
cp "$blob" "$workdir/clock-original.dtbo"
fdtput -t u "$blob" /fragment@0/__overlay__ unexpected-property 1234
reject api set spi1 0 3300000
cmp "$conf" "$workdir/saved"
cp "$workdir/clock-original.dtbo" "$blob"
reject api set spi0 0 40000001
reject api set spi1 1 5000001
reject api set spi1 0 2999
reject api set spi1 2 3000
reject _dt_overlays_write_config "$conf" false ''
cmp "$conf" "$workdir/saved"
api grid spi1 1 > "$workdir/grid"
awk -F '\t' 'NF==2 { if ($1>5000000 || $1<3000) exit 1; count++ } END { if(!count) exit 1 }' "$workdir/grid"
api default spi1 0
check_rates 18000000 40000000 5000000
backup=
for change in "$conf".spi-clocks-backups/change.*; do
    if cmp -s "$change/after" "$conf" && cmp -s "$change/before" "$workdir/saved"; then backup=${change##*/}; fi
done
[[ $backup ]]
echo '# manual change' >> "$conf"
reject api rollback "$backup"
sed -i '$d' "$conf"
api rollback "$backup"
cmp "$conf" "$workdir/saved"
api default-all
check_rates 40000000 40000000 10000000
! fdtget "$workdir/current.dtb" /soc/spi@5011000/nfc@1 armbian,spi-clock-request-hz >/dev/null 2>&1
grep -Fxq 'rootdev=unchanged' "$conf"
echo 'PASS independent SPI0/1 + CS, board/chip limits, idempotence, concurrent updates, provider conflict, reset and rollback'
