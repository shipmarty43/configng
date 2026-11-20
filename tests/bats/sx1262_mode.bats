#!/usr/bin/env bats
setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_sx1262_mode.sh"
    calls="$BATS_TEST_TMPDIR/calls"
    _sx1262_mode_cli() {
        echo "$*" >> "$calls"
        case "$1" in
            profile) echo no-radio ;;
            set) echo "restore result"; [[ "${FAIL:-}" != yes ]] ;;
        esac
    }
    dialog_msgbox() { printf '%s\n' "$2" > "$BATS_TEST_TMPDIR/message"; }
}
@test 'no-radio menu offers all four modes and forwards the selected mode' {
    dialog_menu() {
        [[ "$2" == *'No-radio'* && "$*" == *'off Off meshtastic Meshtastic reticulum Reticulum lorawan LoRaWAN'* ]] || return 1
        echo lorawan
    }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\nset lorawan' ]
}
@test 'cancel makes no change' {
    dialog_menu() { return 1; }
    module_sx1262_mode select
    [ "$(cat "$calls")" = profile ]
}
@test 'hardware profile inspection in no-radio mode never calls set' {
    dialog_menu() { echo check-meshtastic; }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\ncheck-meshtastic' ]
}
@test 'backend failure and rollback result reach the operator' {
    dialog_menu() { echo reticulum; }
    FAIL=yes
    run module_sx1262_mode select
    [ "$status" -ne 0 ]
    [ "$(cat "$BATS_TEST_TMPDIR/message")" = 'restore result' ]
}
