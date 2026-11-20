#!/usr/bin/env bats
setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_gnss.sh"
    log="$BATS_TEST_TMPDIR/calls"
    _gnss_bin() { echo "gnss $*" >> "$log"; [[ "${FAIL_CONFIG:-}" != yes ]]; }
    systemctl() { echo "systemctl $*" >> "$log"; }
}
@test 'GNSS selection persists and starts only its provider' {
    run module_gnss auto
    [ "$status" -eq 0 ]
    [ "$(cat "$log")" = $'gnss configure --mode auto\nsystemctl enable opi-gnss.service\nsystemctl restart opi-gnss.service' ]
}
@test 'GNSS off stops the provider while preserving modem and gpsd' {
    module_gnss off
    [ "$(cat "$log")" = $'gnss configure --mode off\nsystemctl disable --now opi-gnss.service' ]
}
@test 'GNSS invalid configuration never starts a service' {
    FAIL_CONFIG=yes
    run module_gnss modem
    [ "$status" -ne 0 ]
    [ "$(cat "$log")" = 'gnss configure --mode modem' ]
}
@test 'GNSS preference does not start a stopped provider' {
    module_gnss prefer modem
    grep -qx 'systemctl try-restart opi-gnss.service' "$log"
}
