module_options+=(
	["module_zero2w_gpio,author"]="@shipmarty43"
	["module_zero2w_gpio,maintainer"]="@shipmarty43"
	["module_zero2w_gpio,feature"]="module_zero2w_gpio"
	["module_zero2w_gpio,desc"]="Inspect physical header GPIO ownership on Orange Pi Zero 2W"
	["module_zero2w_gpio,example"]="select status help"
	["module_zero2w_gpio,status"]="Preview"
	["module_zero2w_gpio,group"]="Hardware"
)

function _zero2w_gpio_compatible() { cat /sys/firmware/devicetree/base/compatible; }
function _zero2w_gpio_board() {
	local ids
	ids=$(_zero2w_gpio_compatible 2>/dev/null | tr '\0' '\n') || return 1
	grep -Fxq 'xunlong,orangepi-zero2w' <<< "$ids" && grep -Fxq 'allwinner,sun50i-h618' <<< "$ids"
}
function _zero2w_gpio_status() {
	_zero2w_gpio_board || { echo 'Requires Orange Pi Zero 2W with H618.' >&2; return 1; }
	local python
	for python in /opt/wiringpi-zero2w/bin/python3 /usr/bin/python3; do
		if [[ -x "$python" ]] && "$python" -I -c 'import wiringpi_zero2w' 2>/dev/null; then
			"$python" -I -m wiringpi_zero2w
			return $?
		fi
	done
	echo 'Install the WiringPi Zero 2W Python package in /opt/wiringpi-zero2w or in system Python, and its matching libwiringPi.' >&2
	return 1
}
function module_zero2w_gpio() {
	local output rc
	case "${1:-help}" in
		status) _zero2w_gpio_status ;;
		select)
			if output=$(_zero2w_gpio_status 2>&1); then rc=0; else rc=$?; fi
			local -a options=()
			[[ ${DIALOG:-} != whiptail ]] || options+=(--scrolltext)
			dialog_msgbox 'Zero 2W GPIO ownership' "$output" 18 72 "${options[@]}"
			return "$rc" ;;
		help) echo 'module_zero2w_gpio status|select. Shows header pin, sunxi number, direction and kernel consumer.' ;;
		*) echo 'Unknown GPIO action.' >&2; return 1 ;;
	esac
}
