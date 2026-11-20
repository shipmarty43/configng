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
@test 'SPI menu saves typed Hz without switching any service' {
    dialog_menu() { if [[ $1 == 'SPI bus clock' ]]; then echo custom; else echo spi; fi; }
    dialog_inputbox() { echo 500000; }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\nspi\nspi 500000' ]
}
@test 'cancelling SPI clock entry preserves settings' {
    dialog_menu() { if [[ $1 == 'SPI bus clock' ]]; then echo custom; else echo spi; fi; }
    dialog_inputbox() { return 1; }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\nspi' ]
}
@test 'Reticulum inspection in no-radio profile does not activate a worker' {
    dialog_menu() { echo check-reticulum; }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\ncheck-reticulum' ]
}
@test 'diagnostics refresh only issues read requests' {
    dialog_menu() { echo diagnostics; }
    dialog_yesno() {
        [[ -f "$BATS_TEST_TMPDIR/refreshed" ]] && return 1
        touch "$BATS_TEST_TMPDIR/refreshed"; return 0
    }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\ndiagnostics\ndiagnostics' ]
}

@test 'grid row saves its integer request only for the HAT' {
    _sx1262_mode_cli() {
        echo "$*" >> "$calls"
        case "$1" in profile) echo no-radio ;; spi-grid) printf 'model\n1714286\t1714285 Hz  CDR2=6\n' ;; esac
    }
    dialog_menu() {
        case "$1" in 'SX1262 mode') echo spi ;; 'SPI bus clock') echo hat ;; *) echo 1714286 ;; esac
    }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\nspi\nspi-grid hat --menu\nspi 1714286' ]
}
@test 'inspecting controller grid cannot change the saved request' {
    _sx1262_mode_cli() {
        echo "$*" >> "$calls"
        case "$1" in profile) echo no-radio ;; spi) return 1 ;; spi-grid) printf 'model\n100000000\t100 MHz\n' ;; esac
    }
    dialog_menu() {
        case "$1" in 'SX1262 mode') echo spi ;; 'SPI bus clock') echo spi0 ;; *) echo 100000000 ;; esac
    }
    module_sx1262_mode select
    [ "$(cat "$calls")" = $'profile\nspi\nspi-grid spi0 --menu' ]
}
