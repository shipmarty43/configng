#!/usr/bin/env bats

setup() {
	declare -gA module_options=()
	source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_lorawan.sh"
	export LW_TRACE="$BATS_TEST_TMPDIR/trace"
	_lorawan_call() { echo "call $1" >> "$LW_TRACE"; [[ "${FAIL_CALL:-}" != "$1" ]]; }
	_lorawan_systemctl() {
		echo "systemctl $*" >> "$LW_TRACE"
		if [[ "$1" == is-active ]]; then [[ "${3:-}" == "${ACTIVE_UNIT:-}" ]]; else return 0; fi
	}
}
@test 'check performs no service operation' {
	run module_lorawan check
	[ "$status" -eq 0 ]
	[ "$(cat "$LW_TRACE")" = 'call check' ]
}
@test 'invalid configuration prevents service start' {
	FAIL_CALL=preflight
	run module_lorawan start
	[ "$status" -ne 0 ]
	[ "$(cat "$LW_TRACE")" = 'call preflight' ]
}
@test 'missing or invalid state prevents service start' {
	FAIL_CALL=status
	run module_lorawan start
	[ "$status" -ne 0 ]
	! grep -q 'systemctl start' "$LW_TRACE"
}
@test 'active Meshtastic is not stopped or displaced' {
	ACTIVE_UNIT=meshtasticd.service
	run module_lorawan start
	[ "$status" -ne 0 ]
	[[ "$output" == *'Stop the current radio owner first'* ]]
	! grep -Eq 'systemctl (start|stop)' "$LW_TRACE"
}
@test 'valid configuration and state start only the LoRaWAN unit' {
	run module_lorawan start
	[ "$status" -eq 0 ]
	grep -qx 'systemctl start opi-lorawan.service' "$LW_TRACE"
	! grep -Eq 'enable|restart|stop' "$LW_TRACE"
}
@test 'running status does not open a locked state file' {
	ACTIVE_UNIT=opi-lorawan.service
	run module_lorawan status
	[ "$status" -eq 0 ]
	! grep -q '^call status' "$LW_TRACE"
	[[ "$output" == *'does not prove LoRaWAN connectivity'* ]]
}
@test 'stop does not alter configuration or another service' {
	run module_lorawan stop
	[ "$status" -eq 0 ]
	[ "$(cat "$LW_TRACE")" = 'systemctl stop opi-lorawan.service' ]
}
@test 'unknown action is rejected' {
	run module_lorawan reset-counters
	[ "$status" -ne 0 ]
	[ ! -e "$LW_TRACE" ]
}
