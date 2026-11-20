module_options+=(
	["module_ups_dfr0528,author"]="@shipmarty43"
	["module_ups_dfr0528,maintainer"]="@shipmarty43"
	["module_ups_dfr0528,feature"]="module_ups_dfr0528"
	["module_ups_dfr0528,desc"]="DFR0528 UPS boot integration on Orange Pi Zero 2W"
	["module_ups_dfr0528,example"]="select status enable disable help"
	["module_ups_dfr0528,status"]="Preview"
	["module_ups_dfr0528,group"]="Kernel"
)

function _ups_dfr_boot() { echo /boot; }
function _ups_dfr_dt() { echo /sys/firmware/devicetree/base; }
function _ups_dfr_supplies() { echo /sys/class/power_supply; }
function _ups_dfr_board() {
	[[ -r "$(_ups_dfr_dt)/compatible" ]] &&
		tr '\0' '\n' < "$(_ups_dfr_dt)/compatible" | grep -qx 'xunlong,orangepi-zero2w'
}
function _ups_dfr_driver() {
	modinfo -k "$(uname -r)" -F name dfr0528_battery 2>/dev/null | grep -qx dfr0528_battery
}
function _ups_dfr_status() {
	local root path field
	root=$(_ups_dfr_boot)
	_ups_dfr_board || { echo 'DFR0528 boot controls support Orange Pi Zero 2W only.' >&2; return 1; }
	awk '/^(overlays|user_overlays)=/ {print "Next boot: " $0}' "$root/armbianEnv.txt" || return 1
	if _ups_dfr_driver; then echo 'Driver for current kernel: installed'; else echo 'Driver for current kernel: missing'; fi
	if [[ -f "$root/overlay-user/zero2w-dfr0528.dtbo" ]]; then echo 'UPS overlay: installed'; else echo 'UPS overlay: missing'; fi
	local found=false
	for path in "$(_ups_dfr_supplies)"/dfr0528-*; do
		[[ -d "$path" ]] || continue
		found=true
		for field in capacity voltage_now status present; do
			[[ ! -r "$path/$field" ]] || printf 'Live %s: %s\n' "$field" "$(cat "$path/$field")"
		done
	done
	[[ "$found" == true ]] || echo 'No live DFR0528 power_supply; boot selection and live state are separate.'
	echo 'MAX17043 has no charging-status flag. DFR0528 does not export one over I2C.'
	echo 'UPower may infer discharging even with a charger connected. No extra GPIO is used.'
}

# Never source armbianEnv.txt. Compose the complete proposed DT when enabling;
# reject boot routes/fixups this validator cannot reproduce.
function _ups_dfr_validate() {
	local bus=/soc/i2c@5002400 pins=/soc/pinctrl@300b000/i2c1-pi-pins device_status
	device_status=$(fdtget "$1" "$bus/ups@10" status 2>/dev/null || true)
	[[ "$(fdtget "$1" "$bus" status)" == okay &&
	   "$(fdtget "$1" "$bus/ups@10" compatible)" == dfrobot,dfr0528 &&
	   "$(fdtget -t x "$1" "$bus/ups@10" reg)" == 10 &&
	   "$(fdtget "$1" "$pins" pins)" == 'PI7 PI8' &&
	   "$(fdtget "$1" "$pins" function)" == i2c1 &&
	   ( -z "$device_status" || "$device_status" == okay || "$device_status" == ok ) &&
	   "$(fdtget -t x "$1" "$pins" phandle)" == "$(fdtget -t x "$1" "$bus" pinctrl-0)" ]] || {
		echo 'Composed DT does not provide the expected UPS / I2C1 PI7/PI8 route.' >&2; return 1;
	}
}
function _ups_dfr_prepare() { _zero2w_overlay_prepare "$@" ups zero2w-dfr0528; }
function _ups_dfr_change() { _zero2w_overlay_change "$1" ups _ups_dfr_prepare; }

function _ups_dfr_select() {
	local choice output
	while true; do
		choice=$(dialog_menu 'DFR0528 UPS' 'Battery percentage and voltage. Changes apply after reboot; MAX17043 cannot report charging status.' 17 78 6 \
			status 'Show boot selection, driver and live battery' \
			enable 'Enable UPS at boot (requires installed driver and overlay)' \
			disable 'Disable UPS at boot; retain shared I2C bus') || return 0
		case "$choice" in status|enable|disable) ;; *) return 0 ;; esac
		if output=$(module_ups_dfr0528 "$choice" 2>&1); then
			dialog_msgbox 'DFR0528 UPS' "$output" 20 78
		else
			dialog_msgbox 'DFR0528 UPS: not applied' "$output" 20 78
		fi
	done
}
function module_ups_dfr0528() {
	case "${1:-help}" in
		select) _ups_dfr_select ;;
		status) _ups_dfr_status ;;
		enable|disable) _ups_dfr_change "$1" ;;
		help) echo 'module_ups_dfr0528 select|status|enable|disable. Boot controls for installed DFR0528 driver/overlay on Zero 2W; no automatic download or reboot.' ;;
		*) echo 'Unknown UPS command.' >&2; return 1 ;;
	esac
}
