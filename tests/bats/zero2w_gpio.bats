#!/usr/bin/env bats
setup() {
	declare -gA module_options=()
	source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_zero2w_gpio.sh"
}
@test 'match both exact DT strings' {
	_zero2w_gpio_compatible() { printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0'; }
	_zero2w_gpio_board
	_zero2w_gpio_compatible() { printf 'xunlong,orangepi-zero2w-plus\0allwinner,sun50i-h618\0'; }
	! _zero2w_gpio_board
	_zero2w_gpio_compatible() { printf 'xunlong,orangepi-zero2w\0'; }
	run module_zero2w_gpio status
	[ "$status" -eq 1 ]
	[[ "$output" == *'Requires Orange Pi Zero 2W'* ]]
}
@test 'dialog displays the report and propagates discovery failures' {
	_zero2w_gpio_status() { echo 'test report'; return 3; }
	dialog_msgbox() { echo "$2"; }
	run module_zero2w_gpio select
	[ "$status" -eq 3 ]
	[ "$output" = 'test report' ]
}
