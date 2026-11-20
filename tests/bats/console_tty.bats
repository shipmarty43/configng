#!/usr/bin/env bats
setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_console_tty.sh"
    trace="$BATS_TEST_TMPDIR/actions"
    _console_tty_cli() {
        echo "$*" >> "$trace"
        case "$1" in
            list) printf 'tty1\tLocal display VT 1\nttyS7\tUART Example\nttyS7+tty1\tBoth\n' ;;
            set) [[ "$2" != invalid ]] ;;
            backups) echo change.test ;;
        esac
    }
    dialog_msgbox() { :; }
}
@test 'menu offers discovered targets and dispatches combined selection' {
    dialog_menu() {
        [[ "$*" == *'ttyS7+tty1'* ]] || return 1
        echo ttyS7+tty1
    }
    module_console_tty select
    [ "$(cat "$trace")" = $'list\nset ttyS7+tty1' ]
}
@test 'menu cancellation leaves boot settings alone' {
    dialog_menu() { return 1; }
    module_console_tty select
    [ "$(cat "$trace")" = list ]
}
@test 'menu restores the selected backup and propagates CLI failures' {
    dialog_menu() {
        if [[ "$1" == 'Restore console' ]]; then echo change.test; else echo rollback; fi
    }
    module_console_tty select
    [ "$(cat "$trace")" = $'list\nbackups\nrollback change.test' ]
    run module_console_tty set invalid
    [ "$status" -ne 0 ]
}
