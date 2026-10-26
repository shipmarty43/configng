#!/usr/bin/env bats

setup() {
	declare -gA module_options=()
	source "${BATS_TEST_DIRNAME}/../../tools/modules/system/module_cpu_power.sh"
	CPU_FIXTURE="$BATS_TEST_TMPDIR/cpufreq"
	mkdir -p "$CPU_FIXTURE/policy0" "$CPU_FIXTURE/policy4"
	_cpu_power_root() { printf '%s\n' "$CPU_FIXTURE"; }
	local policy
	for policy in policy0 policy4; do
		printf 'ondemand\n' >"$CPU_FIXTURE/$policy/scaling_governor"
		printf 'ondemand performance powersave schedutil userspace\n' >"$CPU_FIXTURE/$policy/scaling_available_governors"
		printf 'cpufreq-dt\n' >"$CPU_FIXTURE/$policy/scaling_driver"
		printf '480000\n' >"$CPU_FIXTURE/$policy/scaling_min_freq"
		printf '1512000\n' >"$CPU_FIXTURE/$policy/scaling_max_freq"
		printf '1512000\n' >"$CPU_FIXTURE/$policy/cpuinfo_max_freq"
		printf '480000 1008000 1512000\n' >"$CPU_FIXTURE/$policy/scaling_available_frequencies"
	done
}

@test "CPU power: status lists all policies without changing files" {
	run module_cpu_power status
	[ "$status" -eq 0 ]
	[[ "$output" == *policy0* && "$output" == *policy4* && "$output" == *cpufreq-dt* ]]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_governor")" = ondemand ]
}

@test "CPU power: governor affects only the selected policy" {
	run module_cpu_power governor policy4 schedutil
	[ "$status" -eq 0 ]
	[ "$(cat "$CPU_FIXTURE/policy4/scaling_governor")" = schedutil ]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_governor")" = ondemand ]
}

@test "CPU power: maximum changes without changing minimum" {
	run module_cpu_power max policy0 1008000
	[ "$status" -eq 0 ]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_max_freq")" = 1008000 ]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_min_freq")" = 480000 ]
}

@test "CPU power: reject invalid governors, policies and missing arguments" {
	for name in bogus 'schedutil performance' '$(touch hacked)'; do
		run module_cpu_power governor policy0 "$name"
		[ "$status" -ne 0 ]
	done
	run module_cpu_power governor ../policy0 performance
	[ "$status" -ne 0 ]
	run module_cpu_power governor policy99 performance
	[ "$status" -ne 0 ]
	run module_cpu_power governor
	[ "$status" -ne 0 ]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_governor")" = ondemand ]
}

@test "CPU power: reject invalid, overflowing and unavailable frequencies before write" {
	for frequency in 0 100000 2000000 999999 -1 abc 1.5 9999999999999999999999; do
		run module_cpu_power max policy0 "$frequency"
		[ "$status" -ne 0 ]
		[ "$(cat "$CPU_FIXTURE/policy0/scaling_max_freq")" = 1512000 ]
	done
}

@test "CPU power: absent table allows driver-controlled range but not overclocking" {
	rm "$CPU_FIXTURE/policy0/scaling_available_frequencies"
	run module_cpu_power max policy0 1000000
	[ "$status" -eq 0 ]
	run module_cpu_power max policy0 1600000
	[ "$status" -ne 0 ]
}

@test "CPU power: missing policies are reported" {
	rm -r "$CPU_FIXTURE"
	run module_cpu_power status
	[ "$status" -ne 0 ]
	[[ "$output" == *'No CPUFreq policies'* ]]
}

@test "CPU power: write failures return failure" {
	rm "$CPU_FIXTURE/policy0/scaling_max_freq"
	mkdir "$CPU_FIXTURE/policy0/scaling_max_freq"
	run module_cpu_power max policy0 1008000
	[ "$status" -ne 0 ]
	[[ "$output" == *'CPUFreq write failed'* ]]
}

@test "CPU power: a driver read-back mismatch is not reported as success" {
	cat() {
		if [[ "$1" == */scaling_governor ]]; then printf 'ondemand\n'; else command cat "$@"; fi
	}
	run module_cpu_power governor policy0 performance
	[ "$status" -ne 0 ]
	[[ "$output" == *'Kernel reports'* ]]
}

@test "CPU power: cancelled menu does not change anything" {
	dialog_menu() { return 1; }
	run module_cpu_power select
	[ "$status" -eq 0 ]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_governor")" = ondemand ]
}

@test "CPU power: menu applies a supported governor without requiring EPP" {
	printf '0\n' >"$BATS_TEST_TMPDIR/menu-step"
	dialog_menu() {
		local step
		step=$(cat "$BATS_TEST_TMPDIR/menu-step")
		printf '%s\n' "$((step + 1))" >"$BATS_TEST_TMPDIR/menu-step"
		case "$step" in 0) echo policy0 ;; 1) echo governor ;; 2) echo powersave ;; esac
	}
	dialog_msgbox() { printf '%s\n' "$*"; }
	run module_cpu_power select
	[ "$status" -eq 0 ]
	[[ "$output" == *'CPU power applied'* ]]
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_governor")" = powersave ]
}
