module_options+=(
	["module_modem,author"]="@shipmarty43"
	["module_modem,maintainer"]="@shipmarty43"
	["module_modem,feature"]="module_modem"
	["module_modem,desc"]="Mobile broadband profiles with ModemManager and NetworkManager"
	["module_modem,example"]="select status profiles show create configure connect connect-ask disconnect autoconnect remove help"
	["module_modem,status"]="Preview"
	["module_modem,group"]="Network"
)
function _modem_nm() { LC_ALL=C nmcli --colors no "$@"; }
function _modem_ready() {
	command -v nmcli >/dev/null && command -v mmcli >/dev/null || {
		echo 'Requires network-manager and modemmanager. No packages or network renderer are changed automatically.' >&2; return 1;
	}
	systemctl is-active --quiet NetworkManager.service && systemctl is-active --quiet ModemManager.service || {
		echo 'NetworkManager and ModemManager must already be running. Keep existing networkd/Netplan management intact until a migration is planned.' >&2; return 1;
	}
}
# mmcli's machine output has padded keys. Filter before exposing any values.
function _modem_field() {
	awk -v wanted="$1" '{i=index($0,":"); if (!i) next; key=substr($0,1,i-1); gsub(/^[ \t]+|[ \t]+$/, "", key); if(key==wanted) {value=substr($0,i+1); sub(/^[ \t]+/, "", value); print value; exit}}'
}
function _modem_ids() (
	set -o pipefail
	LC_ALL=C mmcli --timeout=15 -L -K | awk '{i=index($0,":"); key=substr($0,1,i-1); gsub(/^[ \t]+|[ \t]+$/, "", key); value=substr($0,i+1); gsub(/^[ \t]+|[ \t]+$/, "", value); if (key ~ /^modem-list.value\[[0-9]+\]$/ && value ~ /^\/org\/freedesktop\/ModemManager1\/Modem\/[0-9]+$/) {sub(/^.*\//,"",value); print value}}'
)
function _modem_read() {
	[[ "${1:-}" =~ ^[0-9]{1,8}$ ]] || { echo 'Invalid modem index.' >&2; return 1; }
	LC_ALL=C mmcli --timeout=15 -m "$1" -K
}
function _modem_status() {
	local ids id data
	_modem_ready || return 1
	ids=$(_modem_ids) || return 1
	if [[ -z "$ids" ]]; then
		echo 'No ModemManager modem found. A HiLink/router-style USB device may instead appear as Ethernet; inspect it in Basic network setup.'
		return 0
	fi
	while IFS= read -r id; do
		data=$(_modem_read "$id") || return 1
		printf 'Modem %s\n' "$id"
		printf '%s\n' "$data" | awk '{i=index($0,":"); key=substr($0,1,i-1); gsub(/^[ \t]+|[ \t]+$/, "", key); if (key ~ /^modem\.generic\.(manufacturer|model|state|state-failed-reason|power-state|unlock-required|signal-quality\.value|access-technologies\.value\[[0-9]+\])$/ || key ~ /^modem\.3gpp\.(operator-name|registration-state)$/) print}' | tr -d '\000-\010\013\014\016-\037\177'
	done <<< "$ids"
	_modem_nm -t -f DEVICE,TYPE,STATE device status
}
function _modem_uuid() { [[ "${1:-}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; }
function _modem_owned() {
	_modem_uuid "${1:-}" || { echo 'Expected a profile UUID.' >&2; return 1; }
	[[ "$(_modem_nm -g connection.type connection show uuid "$1")" == gsm &&
		"$(_modem_nm -g connection.stable-id connection show uuid "$1")" == armbian-config-modem-v1 ]] || {
		echo 'Only GSM profiles created by this module can be changed here.' >&2; return 1;
	}
}
function _modem_inactive() {
	local active
	active=$(_modem_nm -g UUID connection show --active) || return 1
	if grep -Fxiq -- "$1" <<< "$active"; then echo 'Disconnect this profile before editing or removing it.' >&2; return 1; fi
}
function _modem_profiles() {
	local ids uuid name
	_modem_ready || return 1
	ids=$(_modem_nm -g UUID connection show) || return 1
	while IFS= read -r uuid; do
		[[ -n "$uuid" ]] || continue
		_modem_owned "$uuid" 2>/dev/null || continue
		name=$(_modem_nm -g connection.id connection show uuid "$uuid") || return 1
		printf '%s\t%s\n' "$uuid" "$name"
	done <<< "$ids"
}
function _modem_show() {
	_modem_ready && _modem_owned "${1:-}" || return 1
	_modem_nm -f connection.id,connection.uuid,connection.autoconnect,gsm.apn,gsm.home-only,ipv4.never-default,ipv6.never-default,ipv4.route-metric,ipv6.route-metric connection show uuid "$1"
}
function _modem_settings_valid() {
	local apn="${1:-}" route="${2:-}" roaming="${3:-}" username="${4:-}"
	[[ ${#apn} -le 100 && "$apn" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$apn" != *..* && "$apn" != *.-* && "$apn" != *-.* ]] || {
		echo 'Enter the APN from your provider (lowercase letters, digits, dots and hyphens).' >&2; return 1;
	}
	[[ "$route" == secondary || "$route" == internet ]] || return 1
	[[ "$roaming" == home || "$roaming" == roaming ]] || return 1
	[[ ${#username} -le 128 && ( -z "$username" || "$username" =~ ^[a-zA-Z0-9_@.+-]+$ ) ]] || return 1
}
# Shared property array is built in the caller's local scope, never eval'ed.
function _modem_settings() {
	local apn="$1" route="$2" roaming="$3" username="${4:-}" never=yes home=yes
	[[ "$route" != internet ]] || never=no
	[[ "$roaming" != roaming ]] || home=no
	settings=(gsm.apn "$apn" gsm.auto-config no gsm.username "$username" gsm.home-only "$home"
		gsm.password-flags 2 gsm.pin-flags 2 ipv4.method auto ipv6.method auto
		ipv4.never-default "$never" ipv6.never-default "$never"
		ipv4.ignore-auto-dns "$never" ipv6.ignore-auto-dns "$never"
		ipv4.route-metric 700 ipv6.route-metric 700 ipv4.dns-priority 700 ipv6.dns-priority 700 connection.metered yes)
}
function _modem_new_uuid() { cat /proc/sys/kernel/random/uuid; }
function _modem_create() {
	local modem="${1:-}" name="${2:-}" apn="${3:-}" route="${4:-secondary}" roaming="${5:-home}" username="${6:-}"
	local data device uuid
	local -a settings
	[[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}$ ]] || { echo 'Profile name: 1–48 letters, digits, underscore or hyphen.' >&2; return 1; }
	_modem_settings_valid "$apn" "$route" "$roaming" "$username" || return 1
	_modem_ready || return 1
	data=$(_modem_read "$modem") || return 1
	device=$(printf '%s\n' "$data" | _modem_field modem.generic.device-identifier)
	[[ "$device" =~ ^[a-fA-F0-9]{40}$ ]] || { echo 'Modem lacks a supported stable device identifier.' >&2; return 1; }
	uuid=$(_modem_new_uuid); _modem_uuid "$uuid" || return 1
	_modem_settings "$apn" "$route" "$roaming" "$username"
	_modem_nm --wait 20 connection add type gsm ifname '*' con-name "armbian-modem-$name" \
		connection.uuid "$uuid" connection.stable-id armbian-config-modem-v1 \
		connection.autoconnect no gsm.device-id "$device" "${settings[@]}" || return 1
	printf 'Profile UUID: %s\nSaved only; connect separately. Autoconnect is disabled.\n' "$uuid"
}
function _modem_configure() {
	local uuid="${1:-}" apn="${2:-}" route="${3:-secondary}" roaming="${4:-home}" username="${5:-}"
	local -a settings
	_modem_settings_valid "$apn" "$route" "$roaming" "$username" || return 1
	_modem_ready && _modem_owned "$uuid" && _modem_inactive "$uuid" || return 1
	_modem_settings "$apn" "$route" "$roaming" "$username"
	# Editing must not reactivate a previously auto-connecting profile.
	_modem_nm --wait 20 connection modify uuid "$uuid" connection.autoconnect no "${settings[@]}" || return 1
	echo 'Profile updated; autoconnect disabled. Connect separately to apply.'
}
function _modem_action() {
	local action="$1" uuid="${2:-}" flag="${3:-}"
	_modem_ready && _modem_owned "$uuid" || return 1
	case "$action" in
		connect) _modem_nm --wait 60 connection up uuid "$uuid" ;;
		connect-ask)
			[[ -t 0 && -t 1 ]] || { echo 'Interactive terminal required for PIN/password prompts.' >&2; return 1; }
			_modem_nm --ask --wait 60 connection up uuid "$uuid" ;;
		disconnect) _modem_nm --wait 20 connection down uuid "$uuid" ;;
		autoconnect)
			[[ "$flag" == yes || "$flag" == no ]] || return 1
			_modem_nm --wait 20 connection modify uuid "$uuid" connection.autoconnect "$flag" ;;
		remove) _modem_inactive "$uuid" && _modem_nm --wait 20 connection delete uuid "$uuid" ;;
		*) return 1 ;;
	esac
}
function _modem_pick_profile() {
	local rows uuid name
	local -a choices=()
	rows=$(_modem_profiles) || return 1
	while IFS=$'\t' read -r uuid name; do [[ -z "$uuid" ]] || choices+=("$uuid" "$name"); done <<< "$rows"
	((${#choices[@]})) || { dialog_msgbox 'Mobile modem' 'No profiles created by this module yet.'; return 1; }
	dialog_menu 'Mobile profile' 'Select the profile UUID.' 20 90 8 -- "${choices[@]}"
}
function _modem_select() {
	local action modem name apn route roaming username uuid flag output result ids id
	local -a choices=()
	_modem_ready || return 1
	action=$(dialog_menu 'Mobile modem' 'Manage mobile broadband without changing Ethernet or Wi-Fi profiles.' 22 80 9 -- \
		status 'SIM, registration and signal' show 'Inspect an APN profile' create 'Create an APN profile' configure 'Edit an inactive APN profile' \
		connect 'Connect (ask for PIN/password if needed)' disconnect 'Disconnect this profile' \
		autoconnect 'Change automatic connection' remove 'Delete an inactive profile') || return 0
	case "$action" in
		status) output=$(_modem_status 2>&1); result=$? ;;
		show) uuid=$(_modem_pick_profile) || return 0; output=$(_modem_show "$uuid" 2>&1); result=$? ;;
		create|configure)
			if [[ "$action" == create ]]; then
				ids=$(_modem_ids) || return 1
				while IFS= read -r id; do [[ -z "$id" ]] || choices+=("$id" "Modem $id"); done <<< "$ids"
				((${#choices[@]})) || { dialog_msgbox 'Mobile modem' 'No modem found. Check status and USB mode.'; return 0; }
				modem=$(dialog_menu 'Modem' 'Select the device shown in Status.' 18 78 6 -- "${choices[@]}") || return 0
				name=$(dialog_inputbox 'Profile name' 'Short name (letters/digits/hyphen/underscore):' 'mobile' 10 78) || return 0
			else uuid=$(_modem_pick_profile) || return 0; fi
			apn=$(dialog_inputbox 'APN' 'APN supplied by your SIM operator:' '' 10 78) || return 0
			username=$(dialog_inputbox 'APN user' 'Username, if required by your operator; otherwise leave empty. No password here.' '' 10 78) || return 0
			route=$(dialog_menu 'Mobile routing' 'Internet allows a default route/DNS and may affect remote access.' 16 78 2 -- secondary 'No default route or carrier DNS' internet 'Internet route, metric 700') || return 0
			roaming=$(dialog_menu 'Roaming' 'Choose according to your plan; national roaming may also require Allow.' 16 78 2 -- home 'Home network only' roaming 'Allow roaming') || return 0
			if [[ "$action" == create ]]; then output=$(_modem_create "$modem" "$name" "$apn" "$route" "$roaming" "$username" 2>&1)
			else output=$(_modem_configure "$uuid" "$apn" "$route" "$roaming" "$username" 2>&1); fi
			result=$? ;;
		connect|disconnect|autoconnect|remove)
			uuid=$(_modem_pick_profile) || return 0
			if [[ "$action" == autoconnect ]]; then
				flag=$(dialog_menu 'Automatic connection' 'Enabling may start a connection immediately and consume mobile data.' 14 78 2 -- no 'Disable' yes 'Enable') || return 0
			fi
			dialog_yesno 'Mobile connection' "Apply $action to the selected profile? Connecting uses mobile data; disconnecting may end a remote session using this modem." 'Apply' 'Cancel' 13 78 --defaultno || return 0
			if [[ "$action" == connect ]]; then
				# Keep native nmcli prompts attached to the terminal, never capture secrets.
				_modem_action connect-ask "$uuid"; result=$?
				output="Connection command finished (exit $result). Check Status for registration and link state."
			else output=$(_modem_action "$action" "$uuid" "$flag" 2>&1); result=$?; fi ;;
		'') return 0 ;;
		*) return 1 ;;
	esac
	dialog_msgbox 'Mobile modem' "$output" 24 90
	return "$result"
}
function module_modem() (
	# Do not put raw modem identifiers or provider fields in shell debug traces.
	# Secrets are handled only by native nmcli prompts, never shell arguments.
	set +x
	case "${1:-help}" in
		status) _modem_status ;;
		profiles) _modem_profiles ;;
		show) _modem_show "${2:-}" ;;
		create) shift; _modem_create "$@" ;;
		configure) shift; _modem_configure "$@" ;;
		connect|connect-ask|disconnect|autoconnect|remove) _modem_action "$@" ;;
		select) _modem_select ;;
		help) printf '%s\n' 'module_modem status|profiles|show UUID|select' \
			'create MODEM NAME APN [secondary|internet] [home|roaming] [USERNAME]' \
			'configure UUID APN [secondary|internet] [home|roaming] [USERNAME]' \
			'connect UUID | connect-ask UUID | disconnect UUID | autoconnect UUID yes|no | remove UUID' \
			"Only this module's GSM profiles are changed. No PIN/password arguments. No service installation or renderer changes." ;;
		*) return 1 ;;
	esac
)
