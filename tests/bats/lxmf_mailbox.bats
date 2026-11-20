#!/usr/bin/env bats
setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_lxmf.sh"
    calls="$BATS_TEST_TMPDIR/calls"
    _lxmf_cli() {
        if [[ "$1" == list ]]; then
            printf '11\tOther\n12\tWorkstation\n'
        else
            echo "$*" >> "$calls"; cat >> "$calls"; echo saved
        fi
    }
    dialog_menu() { echo 12; }
    dialog_msgbox() { :; }
}
@test 'send uses the selected contact id and preserves exact content' {
    dialog_inputbox() {
        if [[ "$2" == *subject* ]]; then echo 'A title'; else printf '%s' 'Привет "$PATH"'; fi
    }
    _lxmf_save send
    [ "$(head -1 "$calls")" = 'send 12' ]
    [ "$(tail -1 "$calls" | jq -r .body)" = 'Привет "$PATH"' ]
}
@test 'cancel composer never queues a message' {
    dialog_inputbox() { return 1; }
    _lxmf_save send
    [ ! -e "$calls" ]
}
@test 'cancelling contact picker never opens composer' {
    dialog_menu() { return 1; }
    dialog_inputbox() { touch "$calls"; }
    _lxmf_save send
    [ ! -e "$calls" ]
}
