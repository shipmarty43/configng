#!/usr/bin/env bats
setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_mesh_local.sh"
    calls="$BATS_TEST_TMPDIR/calls"
    systemctl() { echo "$*" >> "$calls"; [[ ${ACTIVE:-yes} == yes ]]; }
    systemd-run() { echo "$*" >> "$calls"; }
}
@test 'start and stop target only the selected local unit' {
    module_mesh_local meshtastic start
    module_mesh_local reticulum stop
    [ "$(cat "$calls")" = $'start opi-meshtastic-sim.service\nstop opi-reticulum.service' ]
}
@test 'unknown targets and actions never reach systemctl' {
    run module_mesh_local meshtasticd start
    [ "$status" -eq 2 ]
    run module_mesh_local reticulum enable
    [ "$status" -eq 2 ]
    [ ! -e "$calls" ]
}
@test 'inspection does not launch a stopped daemon' {
    ACTIVE=no
    run module_mesh_local meshtastic inspect
    [ "$status" -ne 0 ]
    [ "$(cat "$calls")" = 'is-active --quiet opi-meshtastic-sim.service' ]
}
@test 'inspection uses the simulator network or the Reticulum service identity' {
    module_mesh_local meshtastic inspect
    grep -q 'JoinsNamespaceOf=opi-meshtastic-sim.service.*PrivateNetwork=yes.*sim_info.py' "$calls"
    module_mesh_local reticulum inspect
    grep -q 'User=opi-reticulum.*StateDirectory=opi-reticulum.*rnstatus --config /var/lib/opi-reticulum' "$calls"
}
@test 'cancelling the second dialog leaves both services alone' {
    dialog_menu() {
        if [[ "$2" == 'Choose a software node' ]]; then echo reticulum; else return 1; fi
    }
    module_mesh_local select
    [ ! -e "$calls" ]
}
