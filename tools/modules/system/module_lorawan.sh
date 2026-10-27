module_options+=(
	["module_lorawan,author"]="@shipmarty43"
	["module_lorawan,maintainer"]="@shipmarty43"
	["module_lorawan,feature"]="module_lorawan"
	["module_lorawan,desc"]="Experimental SX1262 EU433 LoRaWAN Class A service"
	["module_lorawan,example"]="select status check start stop help"
	["module_lorawan,status"]="Preview"
	["module_lorawan,group"]="Hardware"
)
function _lorawan_binary() { echo /usr/local/bin/opi-lorawan; }
function _lorawan_config() { echo /etc/opi-lorawan/lorawan.conf; }
function _lorawan_credentials() { echo /etc/opi-lorawan/credentials.conf; }
function _lorawan_state() { echo /var/lib/opi-lorawan; }
function _lorawan_systemctl() { systemctl "$@"; }
function _lorawan_call() {
	[[ -x "$(_lorawan_binary)" ]] || { echo 'Install the optional LoRaWAN component; see hardware/lorawan/README.md.' >&2; return 1; }
	"$(_lorawan_binary)" "$1" "$(_lorawan_config)" "$(_lorawan_credentials)" "$(_lorawan_state)"
}
function _lorawan_status() {
	_lorawan_systemctl show opi-lorawan.service -p LoadState -p ActiveState -p SubState -p Result || return 1
	# The running service owns the state lock. Do not bypass it or report a
	# harmless busy lock as corrupted state.
	if _lorawan_systemctl is-active --quiet opi-lorawan.service; then
		echo 'Service running; inspect journalctl -u opi-lorawan for join/uplink results.'
	else
		_lorawan_call status || return 1
	fi
	echo 'A running process does not prove LoRaWAN connectivity; board/gateway acceptance is pending.'
}
function _lorawan_start() {
	_lorawan_call preflight || return 1
	if _lorawan_systemctl is-active --quiet opi-lorawan.service; then return 0; fi
	_lorawan_call status || return 1
	local unit
	for unit in meshtasticd.service opi-reticulum-radio.service opi-radio-diagnostics.service; do
		if _lorawan_systemctl is-active --quiet "$unit"; then
			echo "Stop the current radio owner first: $unit" >&2; return 1
		fi
	done
	_lorawan_systemctl start opi-lorawan.service
}
function _lorawan_select() {
	local action output result
	action=$(dialog_menu 'LoRaWAN' 'SX1262 EU433 / OTAA / Class A. Install and configure the component first.' 18 80 4 -- \
		status 'Service and saved-state status' check 'Validate configuration without touching hardware' \
		start 'Start configured LoRaWAN radio service' stop 'Stop LoRaWAN radio service') || return 0
	if [[ "$action" == start ]]; then
		dialog_yesno 'Start LoRaWAN' 'Starting joins the configured network and sends the configured payload periodically. The HAT wiring and gateway must be verified.' 'Start' 'Cancel' 12 80 --defaultno || return 0
	fi
	output=$(module_lorawan "$action" 2>&1); result=$?
	dialog_msgbox 'LoRaWAN' "$output" 22 90
	return "$result"
}
function module_lorawan() (
	set +x
	case "${1:-help}" in
		check) _lorawan_call check ;;
		status) _lorawan_status ;;
		start) _lorawan_start ;;
		stop) _lorawan_systemctl stop opi-lorawan.service ;;
		select) _lorawan_select ;;
		help) printf '%s\n' 'module_lorawan select|status|check|start|stop' \
			'Optional EU433 Class A component; hardware/lorawan/README.md has installation and provisioning instructions.' \
			'No credentials in command arguments, automatic counter reset, overlay changes or boot enablement.' ;;
		*) echo 'Unknown LoRaWAN action.' >&2; return 1 ;;
	esac
)
