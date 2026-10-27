module_options+=(
	["module_usb_role,author"]="@shipmarty43"
	["module_usb_role,maintainer"]="@shipmarty43"
	["module_usb_role,feature"]="module_usb_role"
	["module_usb_role,desc"]="USB role diagnostics and Zero 2W USB0 boot role"
	["module_usb_role,example"]="select status boot restore help"
	["module_usb_role,status"]="Preview"
	["module_usb_role,group"]="System"
	["module_usb_role,help_boot"]="Save USB0 role for next boot on Zero 2W: boot host|device"
	["module_usb_role,help_restore"]="Restore the original boot environment without rebooting"
)

# Path functions allow tests to use an isolated boot tree; never source bootenv.
function _usb_role_boot_root() { printf '%s\n' /boot; }
function _usb_role_dt_root() { printf '%s\n' /sys/firmware/devicetree/base; }
function _usb_role_class_root() { printf '%s\n' /sys/class; }
function _usb_role_zero2w() {
	[[ -r "$(_usb_role_dt_root)/compatible" ]] || return 1
	tr '\0' '\n' < "$(_usb_role_dt_root)/compatible" 2>/dev/null | grep -qx 'xunlong,orangepi-zero2w'
}
function _usb_role_available() {
	[[ -d "$(_usb_role_class_root)/udc" || -d "$(_usb_role_class_root)/usb_role" ]] || _usb_role_zero2w
}
function _usb_role_status() {
	local root path value found=false field
	root=$(_usb_role_class_root)
	for path in "$root"/usb_role/*/role "$root"/typec/port*/data_role; do
		[[ -r "$path" ]] || continue
		value=$(cat "$path") || return 1
		printf 'Kernel data role %s: %s\n' "$path" "$value"
		found=true
	done
	[[ "$found" == true ]] || echo 'No kernel role-switch interface exposed; do not infer a role from this alone.'
	found=false
	for path in "$root"/udc/*; do
		[[ -d "$path" ]] || continue
		found=true
		printf 'UDC %s\n' "${path##*/}"
		for field in state function current_speed; do
			[[ ! -r "$path/$field" ]] || printf '  %s: %s\n' "$field" "$(cat "$path/$field")"
		done
	done
	[[ "$found" == true ]] || echo 'No USB device controller registered.'
	if _usb_role_zero2w; then
		path="$(_usb_role_dt_root)/soc/usb@5100000"
		for field in status dr_mode; do
			[[ ! -r "$path/$field" ]] || printf 'Live USB0 DT %s: %s\n' "$field" "$(tr -d '\0' < "$path/$field")"
		done
		echo 'Zero 2W: USB0 supports fixed host/device boot roles. USB1 is host-only.'
		if [[ -f "$(_usb_role_boot_root)/armbianEnv.txt" ]]; then
			awk '/^(fdtfile|overlay_prefix|overlays|user_overlays)=/ {print "Boot config: " $0}' "$(_usb_role_boot_root)/armbianEnv.txt"
		fi
	fi
	echo 'Device role enables a controller, not a gadget function. USB serial/network/storage need separate configuration.'
}

# Validate the known Armbian boot route and actually compose the proposed DT.
# Refuse fixup parameters/custom user overlays: their boot scripts cannot be
# reproduced by fdtoverlay alone. No silent best-effort DT edits.
function _usb_role_prepare() (
	local role="$1" file="$2" out="$3" root line key value prefix='' fdt='' overlays='' users=''
	local item base original overlay work expected name
	local -a selected=() blobs=()
	local -A seen=()
	root=$(_usb_role_boot_root)
	_usb_role_zero2w || { echo 'USB boot control currently supports Orange Pi Zero 2W only.' >&2; return 1; }
	for item in fdtget fdtoverlay; do
		command -v "$item" >/dev/null || { echo 'Install device-tree-compiler for USB boot validation.' >&2; return 1; }
	done
	[[ ! -e "$root/extlinux/extlinux.conf" && -f "$root/boot.scr" ]] || {
		echo 'Unsupported boot route: expected Armbian boot.scr, without extlinux.' >&2; return 1;
	}
	grep -aq 'armbianEnv.txt' "$root/boot.scr" &&
		grep -aFq 'overlay_prefix' "$root/boot.scr" &&
		grep -aFq 'overlay_file}.dtbo' "$root/boot.scr" || {
		echo 'Cannot recognize Armbian overlay loading in boot.scr.' >&2; return 1;
	}
	while IFS= read -r line || [[ -n "$line" ]]; do
		[[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
		[[ "$line" =~ ^([a-zA-Z0-9_]+)=(.*)$ ]] || { echo 'Unsupported boot environment syntax.' >&2; return 1; }
		key=${BASH_REMATCH[1]} value=${BASH_REMATCH[2]}
		case "$key" in
			fdtfile|overlay_prefix|overlays|user_overlays)
				[[ ! -v "seen[$key]" ]] || { echo 'Duplicate USB/DT boot key.' >&2; return 1; }
				seen[$key]=1
				case "$key" in fdtfile) fdt=$value ;; overlay_prefix) prefix=$value ;; overlays) overlays=$value ;; user_overlays) users=$value ;; esac ;;
			param_*|overlaydir|overlay_path|fdt_overlays|fdtfile_*)
				echo 'Boot fixup parameters or custom DT paths require manual USB configuration.' >&2; return 1 ;;
		esac
	done < "$file"
	[[ "$fdt" == allwinner/sun50i-h618-orangepi-zero2w.dtb && "$prefix" == sun50i-h616 && -z "$users" ]] || {
		echo 'Expected explicit Zero 2W fdtfile, sun50i-h616 overlay prefix and no user_overlays.' >&2; return 1;
	}
	[[ "$overlays" =~ ^[a-zA-Z0-9_[:space:]-]*$ && "$overlays" != *$'\n'* ]] || return 1
	read -r -a selected <<< "$overlays"
	overlays=''
	for item in "${selected[@]}"; do
		[[ "$item" != usb0-host ]] || continue
		overlays+="${overlays:+ }$item"
	done
	[[ "$role" != host ]] || overlays+="${overlays:+ }usb0-host"
	base="$root/dtb/$fdt"
	original=$base
	[[ -f "$base" ]] || return 1
	[[ " $(fdtget -t s "$base" / compatible) " == *' xunlong,orangepi-zero2w '* ]] || return 1
	read -r -a selected <<< "$overlays"
	for item in "${selected[@]}"; do
		overlay="$root/dtb/allwinner/overlay/$prefix-$item.dtbo"
		[[ -f "$overlay" ]] || { printf 'Missing overlay: %s\n' "$overlay" >&2; return 1; }
		blobs+=("$overlay")
	done
	work=$(mktemp -d) || return 1
	trap 'rm -rf -- "$work"' EXIT
	if ((${#blobs[@]})); then
		fdtoverlay -i "$base" -o "$work/effective.dtb" "${blobs[@]}" || return 1
	else
		cp -- "$base" "$work/effective.dtb" || return 1
	fi
	base="$work/effective.dtb"
	expected=peripheral; [[ "$role" != host ]] || expected=host
	[[ "$(fdtget -t s "$base" /soc/usb@5100000 dr_mode)" == "$expected" &&
		"$(fdtget -t s "$base" /soc/usb@5100000 status)" == okay &&
		"$(fdtget -t s "$base" /soc/phy@5100400 status)" == okay ]] || {
		echo 'Composed DT does not provide the requested USB0 role/PHY.' >&2; return 1;
	}
	expected=disabled; [[ "$role" != host ]] || expected=okay
	for name in usb@5101000 usb@5101400; do
		[[ "$(fdtget -t s "$base" "/soc/$name" status)" == "$expected" ]] || {
			echo 'Conflicting USB0 EHCI/OHCI configuration.' >&2; return 1;
		}
	done
	# USB1 carries existing peripherals. Reject overlays which alter its role
	# in this constrained backend, even when their names look unrelated.
	for name in usb@5200000 usb@5200400; do
		expected=$(fdtget -t s "$original" "/soc/$name" status) || return 1
		[[ "$(fdtget -t s "$base" "/soc/$name" status)" == "$expected" ]] || {
			echo 'Composed DT changes USB1; this control only manages USB0.' >&2; return 1;
		}
	done
	awk -v roles="$overlays" '/^overlays=/ {print "overlays=" roles; found=1; next} {print} END {if (!found) print "overlays=" roles}' "$file" > "$out"
)

# One pending before/after pair, atomic environment replacement, no reboot.
# The lock serializes this module; compare again before publishing to detect
# ordinary external edits. Other boot editors must not run concurrently.
function _usb_role_change() (
	local action="$1" role="${2:-}" root file backup tmp='' lockfd created=false prepared=false
	root=$(_usb_role_boot_root); file="$root/armbianEnv.txt"; backup="$file.usb-role-backup"
	[[ "$action" == restore || "$action" == boot && ( "$role" == host || "$role" == device ) ]] || return 1
	[[ -f "$file" && ! -L "$file" && ! -L "$file.usb-role.lock" ]] || return 1
	umask 077
	exec {lockfd}>"$file.usb-role.lock" || return 1
	flock -n "$lockfd" || { echo 'Another USB role change is in progress.' >&2; return 1; }
	trap '[[ -z "$tmp" ]] || rm -f -- "$tmp"
		if [[ "$created" == true && "$prepared" == false ]]; then
			rm -f -- "$backup/before" "$backup/after"; rmdir -- "$backup"
		fi' EXIT
	if [[ "$action" == restore ]]; then
		[[ -d "$backup" && ! -L "$backup" && -f "$backup/before" && ! -L "$backup/before" &&
			-f "$backup/after" && ! -L "$backup/after" ]] || { echo 'No complete USB boot backup.' >&2; return 1; }
		cmp -s "$file" "$backup/after" || cmp -s "$file" "$backup/before" || {
			echo 'Boot environment changed externally; preserve it and inspect the backup manually.' >&2; return 1;
		}
		tmp=$(mktemp "$file.restore.XXXXXX") || return 1
		cp --preserve=mode,ownership -- "$backup/before" "$tmp" && sync -f "$tmp" && mv -f -- "$tmp" "$file" || return 1
		tmp=''; sync -f "$file" || return 1
		rm -- "$backup/before" "$backup/after" && rmdir -- "$backup" || return 1
		echo 'Original boot environment restored. Reboot separately to apply.'
		return 0
	fi
	[[ ! -e "$backup" && ! -L "$backup" ]] || { echo 'Restore the pending USB boot backup before another change.' >&2; return 1; }
	mkdir -m 700 -- "$backup" || return 1; created=true
	cp -p -- "$file" "$backup/before" || return 1
	tmp=$(mktemp "$file.usb.XXXXXX") || return 1
	cp --preserve=mode,ownership -- "$file" "$tmp" || return 1
	_usb_role_prepare "$role" "$backup/before" "$tmp" || return 1
	cmp -s "$file" "$tmp" && { echo 'Boot environment already matches.'; return 0; }
	cp -p -- "$tmp" "$backup/after" || return 1
	prepared=true
	sync -f "$backup/before" && sync -f "$backup/after" && sync -f "$tmp" || return 1
	cmp -s "$file" "$backup/before" || { echo 'Boot environment changed during validation; refusing replacement.' >&2; return 1; }
	mv -f -- "$tmp" "$file" || return 1
	tmp=''; sync -f "$file" || return 1
	printf 'USB0 %s saved for NEXT BOOT. Live USB is unchanged.\n' "$role"
	echo 'Check USB0 cabling and power before reboot. Device mode alone does not create a USB gadget.'
)
function _usb_role_select() {
	local action output result
	action=$(dialog_menu 'USB host / device' 'Inspect USB or save the Zero 2W USB0 role for next boot.' 18 78 4 -- \
		status 'Inspect current USB roles and device controller' host 'USB0: host at next boot' \
		device 'USB0: device at next boot' restore 'Restore original boot environment') || return 0
	case "$action" in
		status) output=$(_usb_role_status 2>&1) ;;
		host|device)
			dialog_yesno 'USB0 boot role' "Save USB0 $action for next boot? Disconnect devices first. Host needs suitable power and an OTG adapter; do not connect two powered hosts. Device needs a data cable to a host and a separate gadget function. USB1 is unchanged. The original boot environment will be saved." 'Save' 'Cancel' 18 78 --defaultno || return 0
			output=$(_usb_role_change boot "$action" 2>&1) ;;
		restore) output=$(_usb_role_change restore 2>&1) ;;
		'') return 0 ;;
		*) return 1 ;;
	esac
	result=$?
	dialog_msgbox 'USB role' "$output" 22 78
	return "$result"
}
function module_usb_role() {
	case "${1:-help}" in
		status) _usb_role_status ;;
		select) _usb_role_select ;;
		boot) _usb_role_change boot "${2:-}" ;;
		restore) _usb_role_change restore ;;
		help) printf '%s\n' 'module_usb_role status|select|boot host|boot device|restore' \
			'Boot writes support Zero 2W only; no live role changes or automatic reboot.' \
			'Disconnect USB0 devices and verify power/cabling before reboot. Device role is not a gadget function.' ;;
		*) return 1 ;;
	esac
}
