setup() {
    declare -gA module_options
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_a733_io.sh"
    calls=$BATS_TEST_TMPDIR/calls
    module_a733_io() {
        case "$1" in
            list) printf 'spi3\tenabled pins 23/19/21/26/24\ni2c0\tdisabled pins 5/3\nuart2\tdisabled pins 11/13\n' ;;
            *) echo "$*" >> "$calls" ;;
        esac
    }
    dialog_msgbox() { :; }
}
@test 'SPI3 menu sends distinct CS, Hz and CPOL/CPHA mode' {
    dialog_menu() {
        case "$2" in
            'Select a physical route.'*) echo spi3 ;;
            'Choose the physical chip select.') echo 1 ;;
            'Next-boot settings for this endpoint.') echo set ;;
            'SPI mode (CPOL / CPHA)') echo 3 ;;
            *) return 1 ;;
        esac
    }
    dialog_inputbox() { echo 250000; }
    _a733_menu
    [ "$(cat "$calls")" = 'set spi3-cs1 250000 3' ]
}
@test 'UART boot profile uses the physical route and all four framing fields' {
    dialog_menu() { if [[ $1 == 'Orange Pi Zero 3W header' ]]; then echo uart2; else echo save; fi; }
    _uart_get_framing() { echo '57600 7 even 2'; }
    _a733_menu
    [ "$(cat "$calls")" = 'save uart2 57600 7 even 2' ]
}
@test 'canceling the I2C rate leaves the selection untouched' {
    dialog_menu() { if [[ $1 == 'Orange Pi Zero 3W header' ]]; then echo i2c0; else return 1; fi; }
    _a733_menu
    [ ! -e "$calls" ]
}
