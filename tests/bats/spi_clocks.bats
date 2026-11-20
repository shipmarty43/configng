setup() {
    declare -gA module_options=()
    source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_spi_clocks.sh"
    calls="$BATS_TEST_TMPDIR/calls"
    _spi_clocks_read() {
        printf '%s\n' "$*" >> "$calls"
        case $1 in
            list) printf '0\trohm,dh2228fv\n1\tnxp,pn532\n' ;;
            grid) printf 'example MCLK\n1714286\t1714285 Hz\n' ;;
            status) echo 'Board DT 5000000 Hz' ;;
        esac
    }
    _ups_dfr_board() { return 0; }
    _zero2w_overlay_change() { echo "change $1 ${spi_args[*]}" >> "$calls"; }
    dialog_msgbox() { :; }
}
@test 'device grid forwards the selected physical controller, CS and request' {
    dialog_menu() {
        case "$1" in 'SPI device clocks') echo spi1 ;; 'SPI1 devices') echo 1 ;;
            'SPI1 CS1') echo grid ;; 'SPI clock in Hz') echo 1714286 ;; esac
    }
    module_spi_clocks select
    [ "$(cat "$calls")" = $'list spi1\nstatus spi1 1\ngrid spi1 1\nchange set spi1 1 1714286' ]
}
@test 'cancel a custom clock without changing boot files' {
    dialog_menu() { case "$1" in 'SPI0 devices') echo 0 ;; *) echo custom ;; esac; }
    dialog_inputbox() { return 1; }
    module_spi_clocks select spi0
    [ "$(cat "$calls")" = $'list spi0\nstatus spi0 0' ]
}
@test 'Waveshare CS0 uses the established next-start profile' {
    _spi_clocks_read() { printf '0\tsemtech,sx1262 armbian,spi-dev (SXMD01)\n'; }
    dialog_menu() { echo 0; }
    _sx1262_clock_menu() { echo hat >> "$calls"; }
    module_spi_clocks select spi1
    [ "$(cat "$calls")" = hat ]
}
@test 'empty bus still offers its controller grid without a write' {
    _spi_clocks_read() { :; }
    _sx1262_mode_cli() { echo "$*" >> "$calls"; printf 'model\n100000000\t100 MHz\n'; }
    dialog_menu() { if [[ $1 == 'SPI1 devices' ]]; then echo controller; else return 1; fi; }
    module_spi_clocks select spi1
    [ "$(cat "$calls")" = 'spi-grid spi1 --menu' ]
}
