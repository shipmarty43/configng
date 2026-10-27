module_options+=(
	["module_cpu_power,author"]="@shipmarty43"
	["module_cpu_power,maintainer"]="@shipmarty43"
	["module_cpu_power,feature"]="module_cpu_power"
	["module_cpu_power,desc"]="CPUFreq runtime controls and Armbian boot defaults"
	["module_cpu_power,example"]="select status governor max boot-status persist restore-boot help"
	["module_cpu_power,status"]="Preview"
	["module_cpu_power,group"]="System"
	["module_cpu_power,arch"]="arm64 armhf x86-64 riscv64"
	["module_cpu_power,help_select"]="Select a CPU policy and change its runtime settings"
	["module_cpu_power,help_status"]="Show live CPUFreq policies"
	["module_cpu_power,help_governor"]="Set a supported governor: governor policy0 schedutil"
	["module_cpu_power,help_max"]="Set a maximum frequency in kHz: max policy0 1008000"
	["module_cpu_power,help_persist"]="Save global next-boot defaults with backup: persist schedutil 1008000"
	["module_cpu_power,help_restore-boot"]="Restore saved boot defaults; live settings are unchanged"
	["module_cpu_power,help_boot-status"]="Show Armbian global boot defaults and backup availability"
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

function _cpu_power_validate() {
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
	printf '%s\n' "$attribute"
}

function _cpu_power_set() {
	local name="${1:-}" kind="${2:-}" value="${3:-}" path attribute actual
	attribute=$(_cpu_power_validate "$name" "$kind" "$value") || return 1
	path=$(_cpu_power_policy "$name") || return 1
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

# Armbian's boot service consumes one global policy from this file. Keep the
# distro mechanism rather than installing a second competing CPUFreq service.
function _cpu_power_boot_file() { printf '%s\n' /etc/default/cpufrequtils; }
function _cpu_power_boot_backend() {
	local service
	[[ -f /etc/armbian-release ]] &&
		grep -Fq '/etc/default/cpufrequtils' /usr/lib/armbian/armbian-hardware-optimization || {
		echo 'This image has no supported Armbian CPUFreq boot backend.' >&2
		return 1
	}
	systemctl is-enabled --quiet armbian-hardware-optimize.service || {
		echo 'Armbian hardware optimization is not enabled for boot.' >&2
		return 1
	}
	for service in power-profiles-daemon tuned auto-cpufreq cpufrequtils; do
		if systemctl is-active --quiet "$service.service"; then
			printf 'Another CPU power manager is active: %s. Resolve ownership first.\n' "$service" >&2
			return 1
		fi
	done
}

# Never source the configuration as root. Accept static assignments only.
# Unknown shell syntax must be edited manually rather than silently overwritten.
function _cpu_power_boot_read() {
	local file="$1" line key value
	while IFS= read -r line || [[ -n "$line" ]]; do
		[[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
		if [[ ! "$line" =~ ^[[:space:]]*([A-Z_]+)=(.*)$ ]]; then
			echo 'CPU boot configuration contains unsupported shell syntax.' >&2
			return 1
		fi
		key="${BASH_REMATCH[1]}" value="${BASH_REMATCH[2]}"
		# Strip one matching quote pair, but never expand its contents.
		if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; fi
		[[ "$value" =~ ^[a-zA-Z0-9_-]*$ ]] || {
			echo 'CPU boot configuration contains a non-literal value.' >&2
			return 1
		}
		printf '%s=%s\n' "$key" "$value"
	done < "$file"
}

function _cpu_power_boot_status() {
	local file
	file=$(_cpu_power_boot_file)
	_cpu_power_boot_backend || return 1
	[[ -f "$file" && ! -L "$file" ]] || return 1
	printf 'Armbian boot defaults (all CPU policies): %s\n' "$file"
	_cpu_power_boot_read "$file" || return 1
	[[ ! -d "$file.armbian-config-backup" ]] || echo 'A saved configuration is available for restore-boot.'
	echo 'Boot defaults do not describe current CPUFreq state. Use status for live read-back.'
}

# Runs in a subshell so locking/traps never alter the parent configurator.
function _cpu_power_boot_change() (
	local action="$1" governor="${2:-}" maximum="${3:-}" file backup lockfd temp='' created=false prepared=false
	local name rows key value minimum='' boost='' policies=0
	file=$(_cpu_power_boot_file)
	backup="$file.armbian-config-backup"
	umask 077
	[[ -f "$file" && ! -L "$file" && ! -L "$file.armbian-config.lock" ]] || return 1
	exec {lockfd}>"$file.armbian-config.lock" || return 1
	flock -n "$lockfd" || { echo 'CPU boot settings are being changed by another process.' >&2; return 1; }
	trap '[[ -z "$temp" ]] || rm -f -- "$temp"
		if [[ "$created" == true && "$prepared" == false ]]; then
			rm -f -- "$backup/before" "$backup/after"
			rmdir -- "$backup"
		fi' EXIT
	if [[ "$action" == restore ]]; then
		[[ -d "$backup" && ! -L "$backup" && -f "$backup/before" && -f "$backup/after" ]] || {
			echo 'No complete saved CPU boot configuration.' >&2; return 1;
		}
		# Preserve manual edits. An interrupted write may still match before.
		if ! cmp -s "$file" "$backup/after" && ! cmp -s "$file" "$backup/before"; then
			echo 'Boot configuration changed externally; automatic restore refused. Saved file:' >&2
			printf '%s\n' "$backup/before" >&2; return 1
		fi
		temp=$(mktemp "$file.restore.XXXXXX") || return 1
		cp --preserve=mode,ownership -- "$backup/before" "$temp" && sync -f "$temp" && mv -f -- "$temp" "$file" || return 1
		temp=''
		sync -f "$file" || return 1
		rm -- "$backup/before" "$backup/after" && rmdir -- "$backup" || return 1
		echo 'Original boot defaults restored. Live settings are unchanged; reboot to apply.'
		return 0
	fi
	[[ "$action" == persist ]] || return 1
	_cpu_power_boot_backend || return 1
	[[ ! -e "$backup" && ! -L "$backup" ]] || {
		echo 'Restore the previous saved configuration before saving another profile.' >&2; return 1;
	}
	[[ "$governor" != userspace ]] || {
		echo 'Persistent userspace governor needs a target-frequency controller; unsupported.' >&2; return 1;
	}
	rows=$(_cpu_power_boot_read "$file") || return 1
	while IFS='=' read -r key value; do
		case "$key" in MIN_SPEED) minimum="$value" ;; BOOST) boost="$value" ;; esac
	done <<< "$rows"
	[[ -z "$minimum" || "$minimum" =~ ^[0-9]{1,9}$ ]] || return 1
	[[ -z "$boost" || "$boost" == false ]] || {
		echo 'Disable or manage an existing boost policy manually before using this control.' >&2; return 1;
	}
	while IFS= read -r name; do
		_cpu_power_validate "$name" governor "$governor" > /dev/null || return 1
		_cpu_power_validate "$name" max "$maximum" > /dev/null || return 1
		((policies+=1))
	done < <(_cpu_power_policies)
	((policies > 0)) || return 1
	[[ -z "$minimum" ]] || ((maximum >= 10#$minimum)) || {
		echo 'Maximum is below the saved boot minimum.' >&2; return 1;
	}
	# Prepare complete before/after images before publishing the atomic rename.
	mkdir -m 700 -- "$backup" || return 1
	created=true
	cp -p -- "$file" "$backup/before" || return 1
	temp=$(mktemp "$file.new.XXXXXX") || return 1
	cp --preserve=mode,ownership -- "$file" "$temp" || return 1
	# Validation above has rejected shell commands, expansions and continuations.
	awk '!/^[[:space:]]*(GOVERNOR|MAX_SPEED)=/' "$file" > "$temp" || return 1
	printf '\nGOVERNOR=%s\nMAX_SPEED=%s\n' "$governor" "$maximum" >> "$temp" || return 1
	cp -p -- "$temp" "$backup/after" || return 1
	prepared=true
	sync -f "$backup/before" && sync -f "$backup/after" && sync -f "$temp" || return 1
	mv -f -- "$temp" "$file" || return 1
	temp=''
	sync -f "$file" || return 1
	printf 'Saved for next boot on ALL CPU policies: governor=%s max=%s kHz.\n' "$governor" "$maximum"
	echo 'Live settings unchanged. Use restore-boot to restore the original file.'
)

function _cpu_power_boot_select() {
	local action governor maximum output
	action=$(dialog_menu 'CPU boot defaults' 'Armbian applies these settings to ALL CPU policies at boot.' 18 78 3 -- \
		status 'Inspect boot defaults' persist 'Save governor and maximum for next boot' restore 'Restore saved original defaults') || return 0
	case "$action" in
		status) output=$(_cpu_power_boot_status 2>&1) ;;
		persist)
			governor=$(dialog_inputbox 'Boot governor' 'Governor supported by every CPU policy (for example ondemand or schedutil):' '' 10 78) || return 0
			maximum=$(dialog_inputbox 'Boot maximum' 'Maximum frequency in kHz, supported by every CPU policy:' '' 10 78) || return 0
			dialog_yesno 'Save CPU boot defaults' "Apply $governor / $maximum kHz to all CPU policies at the next boot? The original file will be saved." 'Save' 'Cancel' 12 78 --defaultno || return 0
			output=$(_cpu_power_boot_change persist "$governor" "$maximum" 2>&1)
			;;
		restore) output=$(_cpu_power_boot_change restore 2>&1) ;;
		'') return 0 ;;
		*) return 1 ;;
	esac
	local result=$?
	dialog_msgbox 'CPU boot defaults' "$output"
	return "$result"
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
	name=$(dialog_menu 'CPU power' 'Select a runtime policy or edit global boot defaults.' 18 76 8 "${choices[@]}" boot 'Armbian boot defaults (all policies)') || return 0
	[[ -n "$name" ]] || return 0
	if [[ "$name" == boot ]]; then _cpu_power_boot_select; return $?; fi
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
		boot-status) _cpu_power_boot_status ;;
		persist) _cpu_power_boot_change persist "${2:-}" "${3:-}" ;;
		restore-boot) _cpu_power_boot_change restore ;;
		governor | max) _cpu_power_set "${2:-}" "$1" "${3:-}" ;;
		help)
			printf '%s\n' 'module_cpu_power select|status|governor POLICY NAME|max POLICY KHZ'
			printf '%s\n' 'module_cpu_power boot-status|persist GOVERNOR MAX_KHZ|restore-boot'
			printf '%s\n' 'persist changes global next-boot defaults, with a backup; it does not change the live policy.'
			printf '%s\n' 'governor/max use Linux CPUFreq at runtime and verify by read-back.'
			;;
		*)
			echo 'Unknown CPU power command.' >&2
			return 1
			;;
	esac
}
