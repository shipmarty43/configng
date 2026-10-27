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
function _ups_dfr_prepare() (
	local action="$1" input="$2" output="$3" root line key value name fdt='' prefix='' overlays='' users=''
	local -A seen=()
	local -a stock=() custom=() blobs=()
	root=$(_ups_dfr_boot)
	_ups_dfr_board || { echo 'Expected Orange Pi Zero 2W.' >&2; return 1; }
	[[ -f "$root/boot.scr" && ! -e "$root/extlinux/extlinux.conf" ]] || { echo 'Expected Armbian boot.scr route.' >&2; return 1; }
	grep -aq 'armbianEnv.txt' "$root/boot.scr" && grep -aFq 'overlay-user/${overlay_file}.dtbo' "$root/boot.scr" || {
		echo 'Boot script does not expose the supported user-overlay route.' >&2; return 1;
	}
	while IFS= read -r line || [[ -n "$line" ]]; do
		[[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
		[[ "$line" =~ ^([a-zA-Z0-9_]+)=(.*)$ ]] || { echo 'Unsupported boot environment syntax.' >&2; return 1; }
		key=${BASH_REMATCH[1]} value=${BASH_REMATCH[2]}
		case "$key" in
			overlays|user_overlays|overlay_prefix|fdtfile)
				[[ ! -v "seen[$key]" ]] || { echo "Duplicate DT key: $key" >&2; return 1; }
				seen[$key]=1
				case "$key" in overlays) overlays=$value ;; user_overlays) users=$value ;; overlay_prefix) prefix=$value ;; fdtfile) fdt=$value ;; esac ;;
			param_*|overlaydir|overlay_path|fdt_overlays|fdtfile_*)
				echo 'Custom DT paths or fixup parameters require manual configuration.' >&2; return 1 ;;
		esac
	done < "$input"
	[[ "$prefix" == sun50i-h616 && ( -z "$fdt" || "$fdt" == allwinner/sun50i-h618-orangepi-zero2w.dtb ) ]] || {
		echo 'Unexpected overlay prefix or base DT.' >&2; return 1;
	}
	read -r -a stock <<< "$overlays"
	read -r -a custom <<< "$users"
	for name in "${stock[@]}" "${custom[@]}"; do
		[[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || { echo 'Invalid overlay name.' >&2; return 1; }
	done
	case "$action" in
		enable)
			_ups_dfr_driver || { echo 'Install dfr0528-battery DKMS for the running kernel first; see hardware/dfrobot-ups/README.md.' >&2; return 1; }
			[[ " ${stock[*]} " == *' i2c1-pi '* ]] || stock+=(i2c1-pi)
			[[ " ${custom[*]} " == *' zero2w-dfr0528 '* ]] || custom+=(zero2w-dfr0528)
			for name in fdtget fdtoverlay; do command -v "$name" >/dev/null || { echo 'Install device-tree-compiler first.' >&2; return 1; }; done
			for name in "${stock[@]}"; do blobs+=("$root/dtb/allwinner/overlay/$prefix-$name.dtbo"); done
			for name in "${custom[@]}"; do blobs+=("$root/overlay-user/$name.dtbo"); done
			for name in "${blobs[@]}"; do [[ -f "$name" && ! -L "$name" ]] || { echo "Missing or symlinked overlay: $name" >&2; return 1; }; done
			local composed
			composed=$(mktemp) || return 1
			trap 'rm -f "$composed"' EXIT
			fdtoverlay -i "$root/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb" -o "$composed" "${blobs[@]}" || return 1
			local bus=/soc/i2c@5002400 pins=/soc/pinctrl@300b000/i2c1-pi-pins device_status
			device_status=$(fdtget "$composed" "$bus/ups@10" status 2>/dev/null || true)
			[[ "$(fdtget "$composed" "$bus" status)" == okay &&
			   "$(fdtget "$composed" "$bus/ups@10" compatible)" == dfrobot,dfr0528 &&
			   "$(fdtget -t x "$composed" "$bus/ups@10" reg)" == 10 &&
			   "$(fdtget "$composed" "$pins" pins)" == 'PI7 PI8' &&
			   "$(fdtget "$composed" "$pins" function)" == i2c1 &&
			   ( -z "$device_status" || "$device_status" == okay || "$device_status" == ok ) &&
			   "$(fdtget -t x "$composed" "$pins" phandle)" == "$(fdtget -t x "$composed" "$bus" pinctrl-0)" ]] || {
				echo 'Composed DT does not provide the expected UPS / I2C1 PI7/PI8 route.' >&2; return 1;
			}
			;;
		disable)
			local -a kept=()
			for name in "${custom[@]}"; do [[ "$name" == zero2w-dfr0528 ]] || kept+=("$name"); done
			custom=("${kept[@]}") # Keep shared I2C1 and the installed driver.
			;;
		*) return 1 ;;
	esac
	awk -v stock="${stock[*]}" -v users="${custom[*]}" '
		/^overlays=/ {print "overlays=" stock; s=1; next}
		/^user_overlays=/ {print "user_overlays=" users; u=1; next}
		{print}
		END {if (!s) print "overlays=" stock; if (!u && users != "") print "user_overlays=" users}
	' "$input" > "$output"
)

function _ups_dfr_change() (
	local action="$1" root conf lock work backup
	root=$(_ups_dfr_boot); conf="$root/armbianEnv.txt"; lock="$conf.overlay.lock"
	[[ -f "$conf" && ! -L "$conf" && ! -L "$lock" ]] || { echo 'Unsafe boot configuration path.' >&2; return 1; }
	exec {lockfd}>"$lock" || return 1
	flock -x "$lockfd" || return 1
	work=$(mktemp -d "$root/.ups-change.XXXXXX") || return 1
	trap 'rm -rf "$work"' EXIT
	cp -p "$conf" "$work/before" || return 1
	_ups_dfr_prepare "$action" "$work/before" "$work/after" || return 1
	if cmp -s "$work/before" "$work/after"; then echo 'UPS boot configuration already matches; no change.'; return 0; fi
	cmp -s "$conf" "$work/before" || { echo 'Boot config changed concurrently.' >&2; return 1; }
	[[ ! -L "$conf.ups-backups" ]] || return 1
	mkdir -p -m 700 "$conf.ups-backups" || return 1
	backup=$(mktemp -d "$conf.ups-backups/change.XXXXXX") || return 1
	cp -p "$work/before" "$backup/before" && cp "$work/after" "$backup/after" || return 1
	chmod --reference="$conf" "$work/after" && chown --reference="$conf" "$work/after" || return 1
	sync -f "$backup/before" && sync -f "$backup/after" && sync -f "$work/after" || return 1
	mv "$work/after" "$conf" && sync -f "$root" || return 1
	echo "UPS boot configuration saved. Backup: $backup"
	echo 'Reboot to apply. Live battery monitoring is unchanged until reboot.'
)

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
