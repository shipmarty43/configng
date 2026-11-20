#!/usr/bin/env bats
setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_mesh_mail_ui.sh"
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_meshtastic_mail.sh"
    calls="$BATS_TEST_TMPDIR/calls"
    _meshtastic_mail_cli() {
        if [[ "$1" == list ]]; then printf '123\tFirst [!0000007b]\n234\tSecond [!000000ea]\n'
        else printf '%s\n' "$*" > "$calls"; cat >> "$calls"; echo queued; fi
    }
    dialog_menu() { echo 234; }
    dialog_msgbox() { :; }
}
@test 'composer sends exactly the input bytes to the selected node' {
    dialog_inputbox() { printf '%s' 'Привет "$node"'; }
    _meshtastic_compose
    [ "$(cat "$calls")" = $'send 234\nПривет "$node"' ]
}
@test 'empty selector and cancelled composer never submit' {
    dialog_menu() { return 1; }
    _meshtastic_compose
    [ ! -e "$calls" ]
    dialog_menu() { echo 234; }
    dialog_inputbox() { return 1; }
    _meshtastic_compose
    [ ! -e "$calls" ]
}
