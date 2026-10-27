#!/usr/bin/env bats
setup() {
	declare -gA module_options=()
	source "${BATS_TEST_DIRNAME}/../../tools/modules/network/module_modem.sh"
	MODEM_LOG="$BATS_TEST_TMPDIR/calls"; touch "$MODEM_LOG"
	UUID=12345678-1234-4567-8123-123456789abc
	eval "$(declare -f _modem_ready | sed '1s/_modem_ready/_modem_ready_native/')"
	_modem_ready() { return 0; }
	_modem_new_uuid() { echo "$UUID"; }
	MM_FAIL=0; NM_FAIL=0; PROFILE_TYPE=gsm; PROFILE_OWNER=armbian-config-modem-v1
	ACTIVE_UUID=''; MODEM_EMPTY=no; NO_DEVICE_ID=no
	mmcli() {
		[[ "$MM_FAIL" == 0 ]] || return 7
		if [[ " $* " == *' -L '* ]]; then
			if [[ "$MODEM_EMPTY" == yes ]]; then echo 'modem-list.length : 0'
			else printf 'modem-list.length : 2\nmodem-list.value[1] : /org/freedesktop/ModemManager1/Modem/0\nmodem-list.value[2] : /org/freedesktop/ModemManager1/Modem/3\n'; fi
		else
			printf 'modem.generic.manufacturer : Test Vendor\nmodem.generic.model : Test Modem\nmodem.generic.state : registered\nmodem.generic.unlock-required : sim-pin\nmodem.generic.signal-quality.value : 81\nmodem.3gpp.registration-state : roaming\nmodem.3gpp.operator-name : Test Provider\n'
			printf 'modem.3gpp.imei : PRIVATE-IMEI\nmodem.generic.own-numbers.value[1] : PRIVATE-PHONE\nmodem.3gpp.eps.initial-bearer.settings.password : PRIVATE-PASSWORD\n'
			[[ "$NO_DEVICE_ID" == yes ]] || echo 'modem.generic.device-identifier : 0123456789012345678901234567890123456789'
		fi
		return 0
	}
	_modem_nm() {
		printf '%q ' "$@" >> "$MODEM_LOG"; printf '\n' >> "$MODEM_LOG"
		[[ "$NM_FAIL" == 0 ]] || return 8
		case "$*" in
			'-g UUID connection show') echo "$UUID" ;;
			'-g UUID connection show --active') echo "$ACTIVE_UUID" ;;
			'-g connection.type connection show uuid '*) echo "$PROFILE_TYPE" ;;
			'-g connection.stable-id connection show uuid '*) echo "$PROFILE_OWNER" ;;
			'-g connection.id connection show uuid '*) echo armbian-modem-test ;;
			'-t -f DEVICE,TYPE,STATE device status') echo 'cdc-wdm0:gsm:disconnected' ;;
		esac
		return 0
	}
}
@test 'Modem: structured discovery and filtered status exclude private identifiers and credentials' {
	run _modem_ids
	[ "$status" -eq 0 ]; [ "$output" = $'0\n3' ]
	run module_modem status
	[ "$status" -eq 0 ]
	[[ "$output" == *'Test Modem'* && "$output" == *'sim-pin'* && "$output" == *'roaming'* && "$output" == *81* ]]
	[[ "$output" != *PRIVATE* && "$output" != *0123456789* ]]
	! grep -Eq 'connection (add|modify|up|down|delete)' "$MODEM_LOG"
}
@test 'Modem: no modem distinguishes Ethernet-style devices' {
	MODEM_EMPTY=yes
	run module_modem status
	[ "$status" -eq 0 ]; [[ "$output" == *HiLink* ]]
}
@test 'Modem: default create binds device and never auto-connects or takes default route' {
	run module_modem create 0 mobile internet
	[ "$status" -eq 0 ]; [[ "$output" == *"$UUID"* ]]
	grep -q 'connection.autoconnect no' "$MODEM_LOG"
	grep -q 'gsm.device-id 0123456789012345678901234567890123456789' "$MODEM_LOG"
	grep -q 'ipv4.never-default yes ipv6.never-default yes' "$MODEM_LOG"
	grep -q 'gsm.home-only yes' "$MODEM_LOG"
	grep -q 'gsm.password-flags 2 gsm.pin-flags 2' "$MODEM_LOG"
	! grep -q 'connection up' "$MODEM_LOG"
}
@test 'Modem: Internet and roaming are explicit profile settings' {
	run module_modem create 3 mobile internet internet roaming test@example.org
	[ "$status" -eq 0 ]
	grep -q 'gsm.username test@example.org gsm.home-only no' "$MODEM_LOG"
	grep -q 'ipv4.never-default no ipv6.never-default no' "$MODEM_LOG"
	grep -q 'connection.metered yes' "$MODEM_LOG"
}
@test 'Modem: invalid modem, APN, name, policy and username cause no mutation' {
	for apn in '' 'bad apn' '$(touch bad)' '-option' 'UPPER' 'a..b' 'a.-b'; do
		run module_modem create 0 mobile "$apn"
		[ "$status" -ne 0 ]
	done
	for modem in '-1' '../0' '0;id' ''; do
		run module_modem create "$modem" mobile internet
		[ "$status" -ne 0 ]
	done
	run module_modem create 0 '-bad' internet
	[ "$status" -ne 0 ]
	run module_modem create 0 mobile internet bogus home
	[ "$status" -ne 0 ]
	run module_modem create 0 mobile internet secondary bogus
	[ "$status" -ne 0 ]
	run module_modem create 0 mobile internet secondary home 'user password'
	[ "$status" -ne 0 ]
	[ ! -s "$MODEM_LOG" ]
}
@test 'Modem: missing stable identity refuses a wildcard device profile' {
	NO_DEVICE_ID=yes
	run module_modem create 0 mobile internet
	[ "$status" -ne 0 ]; [ ! -s "$MODEM_LOG" ]
}
@test 'Modem: daemon failures propagate without success messages' {
	MM_FAIL=1
	run module_modem status
	[ "$status" -ne 0 ]
	run module_modem create 0 mobile internet
	[ "$status" -ne 0 ]; [ ! -s "$MODEM_LOG" ]
	MM_FAIL=0; NM_FAIL=1
	run module_modem create 0 mobile internet
	[ "$status" -ne 0 ]; [[ "$output" != *'Saved only'* ]]
}
@test 'Modem: list and management use UUID and ownership marker' {
	run module_modem profiles
	[ "$status" -eq 0 ]; [[ "$output" == *"$UUID"* ]]
	for kind in connection-owner connection-type; do
		PROFILE_OWNER=armbian-config-modem-v1; PROFILE_TYPE=gsm
		if [[ "$kind" == connection-owner ]]; then PROFILE_OWNER=other; else PROFILE_TYPE=802-3-ethernet; fi
		for action in connect disconnect remove; do
			run module_modem "$action" "$UUID"
			[ "$status" -ne 0 ]
		done
	done
	! grep -Eq 'connection (up|down|delete)' "$MODEM_LOG"
}
@test 'Modem: configure only inactive own profile and disable autoconnect' {
	run module_modem configure "$UUID" new.apn internet roaming user
	[ "$status" -eq 0 ]
	grep -q "connection modify uuid $UUID connection.autoconnect no gsm.apn new.apn" "$MODEM_LOG"
	: > "$MODEM_LOG"; ACTIVE_UUID=$UUID
	run module_modem configure "$UUID" new.apn
	[ "$status" -ne 0 ]
	run module_modem remove "$UUID"
	[ "$status" -ne 0 ]
	! grep -Eq 'connection (modify|delete)' "$MODEM_LOG"
}
@test 'Modem: connect and disconnect target only the explicit UUID with bounded waits' {
	run module_modem connect "$UUID"
	[ "$status" -eq 0 ]
	run module_modem disconnect "$UUID"
	[ "$status" -eq 0 ]
	grep -q -- "--wait 60 connection up uuid $UUID" "$MODEM_LOG"
	grep -q -- "--wait 20 connection down uuid $UUID" "$MODEM_LOG"
	! grep -Eq 'radio|device (up|down)|systemctl' "$MODEM_LOG"
}
@test 'Modem: autoconnect requires explicit yes/no and invalid UUID is refused' {
	run module_modem autoconnect "$UUID" yes
	[ "$status" -eq 0 ]
	grep -q "connection modify uuid $UUID connection.autoconnect yes" "$MODEM_LOG"
	: > "$MODEM_LOG"
	run module_modem autoconnect "$UUID" bogus
	[ "$status" -ne 0 ]
	run module_modem connect '--wait'
	[ "$status" -ne 0 ]
	! grep -Eq 'connection (modify|up)' "$MODEM_LOG"
}
@test 'Modem: PIN/password prompting requires a real terminal' {
	run module_modem connect-ask "$UUID"
	[ "$status" -ne 0 ]
	[[ "$output" == *'Interactive terminal required'* ]]
	! grep -q 'connection up' "$MODEM_LOG"
}
@test 'Modem: inactive owned profile removal is scoped by UUID' {
	run module_modem remove "$UUID"
	[ "$status" -eq 0 ]
	grep -q "connection delete uuid $UUID" "$MODEM_LOG"
}
@test 'Modem: cancellation never creates or activates a profile' {
	dialog_menu() { return 1; }
	run module_modem select
	[ "$status" -eq 0 ]; [ ! -s "$MODEM_LOG" ]
	dialog_menu() { echo connect; }
	_modem_pick_profile() { echo "$UUID"; }
	dialog_yesno() { return 1; }
	run module_modem select
	[ "$status" -eq 0 ]; [ ! -s "$MODEM_LOG" ]
}
@test 'Modem: entrypoint suppresses raw modem fields in xtrace' {
	run bash -c 'set -x; declare -A module_options; source "$1"; _modem_ready() { :; }; _modem_ids() { echo 0; }; _modem_read() { echo "modem.3gpp.imei : PRIVATE-IMEI"; }; _modem_nm() { :; }; module_modem status' _ "$BATS_TEST_DIRNAME/../../tools/modules/network/module_modem.sh"
	[ "$status" -eq 0 ]; [[ "$output" != *'+ echo modem.3gpp.imei'* && "$output" != *'data=modem.3gpp.imei'* ]]
}
@test 'Modem: native nmcli offline accepts generated profile properties without D-Bus writes' {
	command -v nmcli >/dev/null || skip 'nmcli required for offline validation'
	_modem_nm() {
		[[ "$1" == --wait && "$3" == connection && "$4" == add ]] || return 1
		shift 2
		command nmcli --offline "$@" > "$BATS_TEST_TMPDIR/native.nmconnection"
	}
	run module_modem create 0 mobile internet internet roaming user
	[ "$status" -eq 0 ]
	grep -q '^type=gsm' "$BATS_TEST_TMPDIR/native.nmconnection"
	grep -q '^autoconnect=false' "$BATS_TEST_TMPDIR/native.nmconnection"
	grep -q '^password-flags=2' "$BATS_TEST_TMPDIR/native.nmconnection"
	grep -q '^pin-flags=2' "$BATS_TEST_TMPDIR/native.nmconnection"
}
@test 'Modem: inactive daemons are reported without changing service or renderer' {
	nmcli() { :; }
	systemctl() { printf '%s\n' "$*" >> "$MODEM_LOG"; return 1; }
	run _modem_ready_native
	[ "$status" -ne 0 ]
	[[ "$output" == *'must already be running'* ]]
	! grep -Eq 'enable|start|restart|netplan' "$MODEM_LOG"
}
@test 'Modem: interactive activation keeps native prompts attached to terminal' {
	command -v script >/dev/null || skip 'util-linux script required'
	cat > "$BATS_TEST_TMPDIR/interactive.sh" <<'SH'
declare -A module_options
source "$MODEM_TEST_SOURCE"
_modem_ready() { :; }
_modem_owned() { :; }
_modem_nm() { printf '%s\n' "$*" > "$MODEM_TEST_CALL"; }
module_modem connect-ask 12345678-1234-4567-8123-123456789abc
SH
	export MODEM_TEST_SOURCE="$BATS_TEST_DIRNAME/../../tools/modules/network/module_modem.sh"
	export MODEM_TEST_CALL="$BATS_TEST_TMPDIR/interactive-call"
	export MODEM_TEST_SCRIPT="$BATS_TEST_TMPDIR/interactive.sh"
	run script -q -e -c 'bash "$MODEM_TEST_SCRIPT"' /dev/null
	[ "$status" -eq 0 ]
	grep -qx -- '--ask --wait 60 connection up uuid 12345678-1234-4567-8123-123456789abc' "$MODEM_TEST_CALL"
}
@test 'Modem: profile inspection requests explicit non-secret fields' {
	run module_modem show "$UUID"
	[ "$status" -eq 0 ]
	grep -Fq 'gsm.apn\,gsm.home-only\,ipv4.never-default' "$MODEM_LOG"
	! grep -Eq 'show-secrets|gsm.pin|gsm.password|gsm.device-id' "$MODEM_LOG"
	PROFILE_OWNER=other
	run module_modem show "$UUID"
	[ "$status" -ne 0 ]
}
