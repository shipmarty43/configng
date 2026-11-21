setup() {
    declare -gA module_options=()
    for mod in i2c_clocks h616_uart h616_pwm; do source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_$mod.sh"; done
    calls="$BATS_TEST_TMPDIR/calls"
    dialog_msgbox() { :; }
    _ups_dfr_board() { return 0; }
}
@test 'I2C grid writes the chosen physical controller and integer request' {
    _bus_clocks_read() {
        case $2 in list) printf 'twi1\tenabled; dfrobot,dfr0528 @10\n' ;; status) echo 'DFR0528' ;;
            grid) printf '24000000 Hz example\n240000\tM=9 N=0\n' ;; esac
    }
    _zero2w_overlay_change() { echo "$1 ${i2c_args[*]}" > "$calls"; }
    dialog_menu() { case "$1" in 'I2C clocks') echo twi1 ;; 'twi1 SCL') echo grid ;; *) echo 240000 ;; esac; }
    module_i2c_clocks select
    [ "$(cat "$calls")" = 'set twi1 240000' ]
}
@test 'UART edit forwards complete framing' {
    _h616_uart_cli() {
        case $1 in list) printf 'ttyS3\tUART2 free\n' ;; status) echo '9600 baud' ;; rates) printf '9600\n115200\n' ;;
            set) echo "$*" > "$calls" ;; esac
    }
    dialog_menu() { case "$1" in 'UART ports') echo ttyS3 ;; ttyS3) echo set ;; 'ttyS3 baud') echo 115200 ;;
        'Data bits') echo 7 ;; Parity) echo even ;; 'Stop bits') echo 2 ;; esac; }
    module_h616_uart select
    [ "$(cat "$calls")" = 'set ttyS3 115200 7 even 2' ]
}
@test 'saving PWM does not start a unit' {
    _h616_pwm_cli() { [[ $1 == status ]] || echo "$*" >> "$calls"; }
    _pwm_list() { printf 'pwm1\tNext boot: PI11\n'; }
    dialog_menu() { case "$1" in 'Header PWM') echo pwm1 ;; PWM1) echo set ;; *) echo inversed ;; esac; }
    dialog_inputbox() { case "$1" in 'PWM frequency') echo 1000 ;; *) echo 37.5 ;; esac; }
    systemctl() { echo unexpected >> "$calls"; return 1; }
    module_h616_pwm select
    [ "$(cat "$calls")" = 'set 1000 37.5 inversed' ]
}
@test 'a currently disabled header port can be selected and saved for next boot' {
    _uart_routes_list() { printf 'uart3\tTX/RX 28/27; disabled\n'; }
    _h616_uart_cli() {
        case $1 in list) : ;; saved) echo 'No saved boot profile' ;; rates) echo 57600 ;; save) echo "$*" > "$calls" ;; esac
    }
    dialog_menu() {
        case "$1" in 'UART ports') echo boot ;; 'UART boot configuration') echo uart3 ;;
            'uart3 boot settings') echo save ;; 'uart3 baud') echo 57600 ;; 'Data bits') echo 7 ;;
            'Parity') echo even ;; 'Stop bits') echo 2 ;; esac
    }
    module_h616_uart select
    [ "$(cat "$calls")" = 'save uart3 57600 7 even 2' ]
}

@test 'profile uses selected PWM4 and does not start a service' {
    _pwm_list() { printf 'pwm4\tNext boot: PI14\n'; }
    _h616_pwm_cli() {
        if [[ $3 != status ]]; then echo "$*" >> "$calls"; fi
    }
    dialog_menu() { case "$1" in 'Header PWM') echo pwm4 ;; PWM4) echo set ;; *) echo normal ;; esac; }
    dialog_inputbox() { case "$1" in 'PWM frequency') echo 20000 ;; *) echo 25 ;; esac; }
    systemctl() { echo unexpected >> "$calls"; return 1; }
    module_h616_pwm select
    [ "$(cat "$calls")" = '--channel 4 set 20000 25 normal' ]
}
@test 'PWM overlay cancellation leaves boot file alone' {
    _h616_pwm_cli() { echo 'PWM2'; }
    _pwm_route_cli() { printf 'PI12\tPhysical 33\n'; }
    dialog_menu() { case "$1" in PWM2) echo route ;; *) return 1 ;; esac; }
    _zero2w_overlay_change() { echo unexpected > "$calls"; }
    module_h616_pwm pwm2
    [ ! -e "$calls" ]
}

@test 'a boot configuration error still allows stopping a live channel' {
    _pwm_list() { echo 'unsupported boot file'; return 1; }
    _h616_pwm_cli() { echo 'line status'; }
    systemctl() { echo "$*" > "$calls"; }
    dialog_menu() { case "$1" in 'Header PWM') echo pwm3 ;; *) echo stop ;; esac; }
    module_h616_pwm select
    [ "$(cat "$calls")" = 'stop opi-zero2w-pwm@3.service' ]
}

@test 'Zero 2W UART2 PH handshake is a distinct boot route' {
    _uart_routes_list() { printf 'uart2\tTX/RX 15/22; disabled\n'; }
    _h616_uart_cli() { [[ $1 == saved ]] && echo 'No saved boot profile'; }
    dialog_menu() {
        case "$1" in 'UART boot configuration') echo uart2 ;; 'uart2 boot settings') echo enable-rtscts-ph ;; esac
    }
    module_h616_uart() { echo "$*" > "$calls"; }
    _uart_boot_menu
    [ "$(cat "$calls")" = 'enable-rtscts-ph uart2' ]
}
