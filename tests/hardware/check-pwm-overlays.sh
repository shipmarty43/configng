#!/usr/bin/env bash
# Regular board image files only. The stock overlay set is copied to a sandbox.
set -euo pipefail
[[ $# == 3 && -f $1 && -d $2 && -f $3 ]] || { echo "Usage: $0 BOARD.dtb STOCK_OVERLAY_DIR boot.scr" >&2; exit 2; }
root=$(cd "$(dirname "$0")/../.." && pwd)
script_dir="$root/bin"; declare -A module_options
for m in devicetree_overlays ups_dfr0528 sx1262_overlay spi_clocks i2c_clocks h616_uart h616_pwm; do
    source "$root/tools/modules/system/module_$m.sh"
done
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
bootroot="$tmp/boot"; conf="$bootroot/armbianEnv.txt"; dt="$bootroot/dtb/allwinner"
mkdir -p "$dt/overlay" "$bootroot/overlay-user" "$tmp/live"
cp "$1" "$dt/sun50i-h618-orangepi-zero2w.dtb"; cp "$3" "$bootroot/boot.scr"
for ov in pwm1-pi11 pwm1-ph3 pwm2-pi12 pwm2-ph2 pwm3-pi13 pwm3-ph0 pwm4-pi14 pwm4-ph1 uart4-pi uart5 i2c1-pi; do
    cp "$2/sun50i-h616-$ov.dtbo" "$dt/overlay/"
done
dtc -q -@ -I dts -O dtb -o "$bootroot/overlay-user/zero2w-dfr0528.dtbo" "$root/hardware/dfrobot-ups/zero2w-dfr0528.dts"
_ups_dfr_boot() { echo "$bootroot"; }
_ups_dfr_dt() { echo "$tmp/live"; }
printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$tmp/live/compatible"
printf 'overlay_prefix=sun50i-h616\nconsole=both\noverlays=i2c1-pi\nuser_overlays=zero2w-dfr0528\n' > "$conf"
pwm() { module_h616_pwm "$@"; }
uart() { module_h616_uart "$@"; }
reject() { if "$@"; then echo "Unexpected success: $*" >&2; exit 1; fi; }
# Substitute only the physical ownership probe (the testing host's GPS/getty
# is unrelated); the boot script, console selection and DT checks remain real.
_pwm_owners_test() {
    PYTHONPATH="$script_dir/../share/armbian-config" python3 - "$@" <<'PY'
import sys
from unittest.mock import patch
import pwm_routes as routes
with patch.object(routes, "release_live_check"):
    try:
        routes.main()
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
PY
}
_pwm_route_cli() { _pwm_owners_test "$@"; }
reject pwm release-uart0
reject pwm pwm3 route PH0
reject pwm pwm4 route PH1
for n in 1 2 3 4; do pwm "pwm$n" route "PI$((n+10))"; done
pwm routes > "$tmp/all"
[[ $(grep -c 'Next boot: PI' "$tmp/all") == 4 ]]
cp "$conf" "$tmp/pi"
pwm pwm2 route PI12; cmp "$conf" "$tmp/pi"
reject uart enable uart4; cmp "$conf" "$tmp/pi"
reject _dt_overlays_write_config "$conf" false 'i2c1-pi pwm1-ph3 pwm1-pi11'
cmp "$conf" "$tmp/pi"
pwm pwm1 route PH3
reject uart enable uart5
pwm pwm1 route off
uart enable uart5
cp "$conf" "$tmp/uart5"
reject pwm pwm2 route PH2; cmp "$conf" "$tmp/uart5"
uart disable uart5
pwm pwm3 route off; pwm pwm4 route off
uart enable uart4
cp "$conf" "$tmp/uart4"
reject pwm pwm3 route PI13; reject pwm pwm4 route PI14; cmp "$conf" "$tmp/uart4"
uart disable uart4
# Model the already released Linux console and a free UART0.
sed -i 's/^console=both/console=custom\nconsoleargs=console=tty1/' "$conf"
# The composed-DT validator consults live owners only when a new release is
# committed. The test host may have its own ttyS0; stub that probe in verify.
_zero2w_check_pwm() (
    local candidate=$1 composed
    composed=$(mktemp); trap 'rm -f "$composed"' EXIT
    _zero2w_overlay_prepare compose "$candidate" "$composed" pwm '' &&
        _pwm_owners_test verify "$composed" "$candidate" "$bootroot"
)
pwm release-uart0
for pair in '1 PH3' '2 PH2' '3 PH0' '4 PH1'; do read -r n pin <<< "$pair"; pwm "pwm$n" route "$pin"; done
pwm routes > "$tmp/ph"; [[ $(grep -c 'Next boot: PH' "$tmp/ph") == 4 ]]
cp "$conf" "$tmp/all-ph"
reject pwm restore-uart0; cmp "$conf" "$tmp/all-ph"
pwm pwm4 route off
id=
for dir in "$conf".pwm-backups/change.*; do
    if cmp -s "$dir/before" "$tmp/all-ph" && cmp -s "$dir/after" "$conf"; then id=${dir##*/}; fi
done
[[ $id ]]; echo '# manual edit' >> "$conf"; reject pwm boot-rollback "$id"
sed -i '$d' "$conf"; pwm boot-rollback "$id"; cmp "$conf" "$tmp/all-ph"
pwm pwm3 route off; pwm pwm4 route off; pwm restore-uart0
_zero2w_overlay_prepare compose "$conf" "$tmp/final" pwm ''
[[ $(fdtget "$tmp/final" /soc/serial@5000000 status) == okay ]]
[[ $(fdtget "$tmp/final" /soc/i2c@5002400/ups@10 compatible) == dfrobot,dfr0528 ]]
[[ $(fdtget "$tmp/final" /ac300-clk clock-frequency) == 2000000 ]]
echo 'PASS eight routes; UART0/4/5 conflicts; two-way route checks; console guard, guarded rollback and UPS/Ethernet coexistence'
