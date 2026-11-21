setup() {
    declare -gA module_options
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_header_gpio.sh"
    calls=$BATS_TEST_TMPDIR/calls
    _ups_dfr_board() { return 1; }
    module_header_gpio() {
        case $1 in
            list) printf '16\tPL2 (r_pio)\n' ;;
            info) echo 'PL2 shared bank L' ;;
            get) echo 'down 20 244' ;;
            *) echo "$*" > "$calls" ;;
        esac
    }
    dialog_msgbox() { :; }
}
@test 'GPIO menu submits physical pin and independent values with microsecond debounce' {
    dialog_menu() {
        case $1 in
            'GPIO header') echo 16 ;; 'GPIO pin 16') echo set ;;
            'Internal bias') echo up ;; 'Drive strength') echo 30 ;;
        esac
    }
    dialog_inputbox() { [[ $3 == 244 ]]; echo 488; }
    _header_gpio_menu
    [ "$(cat "$calls")" = 'set 16 up 30 488' ]
}
@test 'cancelled GPIO debounce prompt never changes the boot selection' {
    dialog_menu() {
        case $1 in 'GPIO header') echo 16 ;; 'GPIO pin 16') echo set ;; 'Internal bias') echo off ;; *) echo default ;; esac
    }
    dialog_inputbox() { return 1; }
    _header_gpio_menu
    [ ! -e "$calls" ]
}
