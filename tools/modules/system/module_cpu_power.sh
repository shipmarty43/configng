module_options+=(
	["module_cpu_power,author"]="@shipmarty43"
	["module_cpu_power,maintainer"]="@shipmarty43"
	["module_cpu_power,feature"]="module_cpu_power"
	["module_cpu_power,desc"]="Runtime CPUFreq governors and frequency limits"
	["module_cpu_power,example"]="select status governor max help"
	["module_cpu_power,status"]="Preview"
	["module_cpu_power,group"]="System"
	["module_cpu_power,arch"]="arm64 armhf x86-64 riscv64"
	["module_cpu_power,help_select"]="Select a CPU policy and change its runtime settings"
	["module_cpu_power,help_status"]="Show live CPUFreq policies"
	["module_cpu_power,help_governor"]="Set a supported governor: governor policy0 schedutil"
	["module_cpu_power,help_max"]="Set a maximum frequency in kHz: max policy0 1008000"
)

# Kept as a function so tests can substitute a temporary sysfs fixture.
function _cpu_power_root() {
	printf '%s\n' /sys/devices/system/cpu/cpufreq
}

function _cpu_power_policies() {
	local path name
	for path in "$(_cpu_power_root)"/policy[0-9]*; do
		name="${path##*/}"
		[[ "$name" =~ ^policy[0-9]+$ && -r "$path/scaling_governor" ]] || continue
		printf '%s\n' "$name"
	done
}

function _cpu_power_available() {
	[[ -n "$(_cpu_power_policies)" ]]
}

function _cpu_power_policy() {
	local name="${1:-}" path
	[[ "$name" =~ ^policy[0-9]+$ ]] || {
		echo 'Invalid CPU policy name.' >&2
		return 1
	}
	path="$(_cpu_power_root)/$name"
	[[ -r "$path/scaling_governor" ]] || {
		echo 'CPUFreq policy is unavailable.' >&2
		return 1
	}
	printf '%s\n' "$path"
}

function _cpu_power_status() {
	local name path field value
	_cpu_power_available || {
		echo 'No CPUFreq policies available.'
		return 1
	}
	while IFS= read -r name; do
		path="$(_cpu_power_policy "$name")" || return 1
		printf '%s\n' "$name"
		for field in scaling_driver scaling_governor scaling_cur_freq scaling_min_freq scaling_max_freq scaling_available_governors scaling_available_frequencies; do
			if [[ -r "$path/$field" ]]; then
				value=$(cat "$path/$field") || return 1
				printf '  %s: %s\n' "$field" "$value"
			fi
		done
	done < <(_cpu_power_policies)
	printf '%s\n' 'Frequencies are in kHz. Changes are runtime-only; other power services may override them.'
}

function _cpu_power_set() {
	local name="${1:-}" kind="${2:-}" value="${3:-}" path attribute raw minimum maximum actual
	local -a available
	path="$(_cpu_power_policy "$name")" || return 1
	case "$kind" in
		governor)
			[[ "$value" =~ ^[a-zA-Z0-9_-]+$ ]] || {
				echo 'Invalid governor name.' >&2
				return 1
			}
			raw=$(cat "$path/scaling_available_governors") || return 1
			read -r -a available <<< "$raw"
			local found=false item
			for item in "${available[@]}"; do [[ "$item" == "$value" ]] && found=true; done
			[[ "$found" == true ]] || {
				echo 'Governor is not supported by this policy.' >&2
				return 1
			}
			attribute=scaling_governor
			;;
		max)
			[[ "$value" =~ ^[1-9][0-9]{0,8}$ ]] || {
				echo 'Frequency must be a positive integer in kHz.' >&2
				return 1
			}
			minimum=$(cat "$path/scaling_min_freq") || return 1
			maximum=$(cat "$path/cpuinfo_max_freq") || return 1
			[[ "$minimum" =~ ^[0-9]{1,9}$ && "$maximum" =~ ^[0-9]{1,9}$ ]] || return 1
			((value >= 10#$minimum && value <= 10#$maximum)) || {
				echo 'Frequency is outside current minimum / hardware maximum.' >&2
				return 1
			}
			if [[ -f "$path/scaling_available_frequencies" ]]; then
				raw=$(cat "$path/scaling_available_frequencies") || return 1
				read -r -a available <<< "$raw"
				local matched=false frequency
				for frequency in "${available[@]}"; do [[ "$frequency" == "$value" ]] && matched=true; done
				[[ "$matched" == true ]] || {
					echo 'Frequency is absent from the kernel table.' >&2
					return 1
				}
			fi
			attribute=scaling_max_freq
			;;
		*)
			echo 'Unknown CPUFreq setting.' >&2
			return 1
			;;
	esac
	printf '%s\n' "$value" > "$path/$attribute" || {
		echo 'CPUFreq write failed; check OS permissions.' >&2
		return 1
	}
	actual=$(cat "$path/$attribute") || return 1
	[[ "$actual" == "$value" ]] || {
		printf 'Kernel reports %s=%s, requested %s; check the driver and other power managers.\n' "$attribute" "$actual" "$value" >&2
		return 1
	}
	printf '%s: %s=%s (runtime only)\n' "$name" "$attribute" "$actual"
}

function _cpu_power_select() {
	local name path action value current minimum maximum item output
	local -a choices=() values=()
	while IFS= read -r name; do
		path="$(_cpu_power_policy "$name")" || return 1
		current=$(cat "$path/scaling_governor") || return 1
		choices+=("$name" "$current")
	done < <(_cpu_power_policies)
	if ((${#choices[@]} == 0)); then
		dialog_msgbox 'CPU power' 'No CPUFreq policies available.'
		return 0
	fi
	name=$(dialog_menu 'CPU power' 'Select a CPU policy. Changes are runtime-only.' 18 76 8 "${choices[@]}") || return 0
	[[ -n "$name" ]] || return 0
	path="$(_cpu_power_policy "$name")" || return 1
	action=$(dialog_menu 'CPU power' 'Choose a setting to apply immediately. Voltage and thermal protection are unchanged.' 18 76 4 \
		governor 'CPU frequency governor' max 'Maximum frequency' status 'Show live policies') || return 0
	[[ -n "$action" ]] || return 0
	choices=()
	case "$action" in
		governor)
			read -r -a values < "$path/scaling_available_governors" || return 1
			current=$(cat "$path/scaling_governor") || return 1
			for item in "${values[@]}"; do
				# userspace requires a target-frequency control not provided here.
				[[ "$item" == userspace ]] && continue
				choices+=("$item" "${item} governor")
			done
			;;
		max)
			if [[ ! -r "$path/scaling_available_frequencies" ]]; then
				dialog_msgbox 'CPU power' 'The driver does not provide a frequency table. Governor controls are still available.'
				return 0
			fi
			read -r -a values < "$path/scaling_available_frequencies" || return 1
			current=$(cat "$path/scaling_max_freq") || return 1
			minimum=$(cat "$path/scaling_min_freq") || return 1
			maximum=$(cat "$path/cpuinfo_max_freq") || return 1
			[[ "$minimum" =~ ^[0-9]{1,9}$ && "$maximum" =~ ^[0-9]{1,9}$ ]] || return 1
			for item in "${values[@]}"; do
				[[ "$item" =~ ^[1-9][0-9]{0,8}$ ]] || continue
				((item >= 10#$minimum && item <= 10#$maximum)) || continue
				choices+=("$item" "$((item / 1000)) MHz")
			done
			;;
		status)
			output=$(_cpu_power_status) || return 1
			dialog_msgbox 'CPU policies' "$output" 22 78
			return 0
			;;
		*) return 1 ;;
	esac
	if ((${#choices[@]} == 0)); then
		dialog_msgbox 'CPU power' 'No supported choices for this setting.'
		return 0
	fi
	value=$(dialog_menu "CPU power: $name" "Current $action: $current. Select the new value." 20 76 10 "${choices[@]}") || return 0
	[[ -n "$value" ]] || return 0
	if output=$(_cpu_power_set "$name" "$action" "$value" 2>&1); then
		dialog_msgbox 'CPU power applied' "$output"
	else
		dialog_msgbox 'CPU power change failed' "$output"
		return 1
	fi
}

function module_cpu_power() {
	case "${1:-help}" in
		select) _cpu_power_select ;;
		status) _cpu_power_status ;;
		governor | max) _cpu_power_set "${2:-}" "$1" "${3:-}" ;;
		help)
			printf '%s\n' 'module_cpu_power select|status|governor POLICY NAME|max POLICY KHZ'
			printf '%s\n' 'Uses Linux CPUFreq; changes are runtime-only and verified by read-back.'
			;;
		*)
			echo 'Unknown CPU power command.' >&2
			return 1
			;;
	esac
}
