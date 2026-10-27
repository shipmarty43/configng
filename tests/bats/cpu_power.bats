#!/usr/bin/env bats

setup() {
	declare -gA module_options=()
	source "${BATS_TEST_DIRNAME}/../../tools/modules/system/module_cpu_power.sh"
	CPU_FIXTURE="$BATS_TEST_TMPDIR/cpufreq"
	mkdir -p "$CPU_FIXTURE/policy0" "$CPU_FIXTURE/policy4"
	_cpu_power_root() { printf '%s\n' "$CPU_FIXTURE"; }
	BOOT_FILE="$BATS_TEST_TMPDIR/cpufrequtils"
	printf '# original defaults\nENABLE=false\nMIN_SPEED=480000\nMAX_SPEED=1512000\nGOVERNOR="ondemand"\nBOOST=false\n' > "$BOOT_FILE"
	cp "$BOOT_FILE" "$BOOT_FILE.original"
	_cpu_power_boot_file() { printf '%s\n' "$BOOT_FILE"; }
	_cpu_power_boot_backend() { return 0; }
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

@test "CPU boot: persists global defaults without changing live state; exact restore" {
	run module_cpu_power persist schedutil 1008000
	[ "$status" -eq 0 ]
	grep -Fxq GOVERNOR=schedutil "$BOOT_FILE"
	grep -Fxq MAX_SPEED=1008000 "$BOOT_FILE"
	grep -Fxq MIN_SPEED=480000 "$BOOT_FILE"
	grep -Fxq BOOST=false "$BOOT_FILE"
	cmp "$BOOT_FILE.original" "$BOOT_FILE.armbian-config-backup/before"
	[ "$(cat "$CPU_FIXTURE/policy0/scaling_governor")" = ondemand ]
	run module_cpu_power boot-status
	[ "$status" -eq 0 ]
	[[ "$output" == *'all CPU policies'* && "$output" == *restore-boot* ]]
	run module_cpu_power restore-boot
	[ "$status" -eq 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	[ ! -d "$BOOT_FILE.armbian-config-backup" ]
}

@test "CPU boot: validates every policy before writing anything" {
	echo 'powersave performance' > "$CPU_FIXTURE/policy4/scaling_available_governors"
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	[ ! -e "$BOOT_FILE.armbian-config-backup" ]
}

@test "CPU boot: rejects arguments, userspace and boost without modifying defaults" {
	for args in 'bogus 1008000' 'schedutil 99999999999999999' 'userspace 1008000' 'schedutil -1'; do
		read -r -a params <<< "$args"
		run module_cpu_power persist "${params[@]}"
		[ "$status" -ne 0 ]
		cmp "$BOOT_FILE" "$BOOT_FILE.original"
	done
	echo 'BOOST=true' >> "$BOOT_FILE"
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	[ ! -e "$BOOT_FILE.armbian-config-backup" ]
}

@test "CPU boot: honours stored minimum and rejects shell syntax without executing it" {
	echo 'MIN_SPEED=1512000' >> "$BOOT_FILE"
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	printf 'GOVERNOR=$(touch %s/pwned)\n' "$BATS_TEST_TMPDIR" >> "$BOOT_FILE"
	run module_cpu_power persist schedutil 1512000
	[ "$status" -ne 0 ]
	[ ! -e "$BATS_TEST_TMPDIR/pwned" ]
	[ ! -e "$BOOT_FILE.armbian-config-backup" ]
}

@test "CPU boot: restore preserves external edits and previous backup" {
	module_cpu_power persist schedutil 1008000
	echo '# user edit' >> "$BOOT_FILE"
	cp "$BOOT_FILE" "$BOOT_FILE.edited"
	run module_cpu_power restore-boot
	[ "$status" -ne 0 ]
	[[ "$output" == *externally* ]]
	cmp "$BOOT_FILE" "$BOOT_FILE.edited"
	cmp "$BOOT_FILE.original" "$BOOT_FILE.armbian-config-backup/before"
	run module_cpu_power persist powersave 480000
	[ "$status" -ne 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.edited"
}

@test "CPU boot: a failed final rename keeps the original and allows recovery" {
	mv() { return 1; }
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	unset -f mv
	run module_cpu_power restore-boot
	[ "$status" -eq 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
}

@test "CPU boot: refuses symbolic links and competing backend before changing file" {
	_cpu_power_boot_backend() { echo 'power manager conflict' >&2; return 1; }
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	_cpu_power_boot_backend() { return 0; }
	rm "$BOOT_FILE"
	ln -s "$BOOT_FILE.original" "$BOOT_FILE"
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	[ -L "$BOOT_FILE" ]
}

@test "CPU boot: cancellation of save leaves boot file unchanged" {
	dialog_menu() { echo persist; }
	dialog_inputbox() { echo schedutil; }
	dialog_yesno() { return 1; }
	run _cpu_power_boot_select
	[ "$status" -eq 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	[ ! -e "$BOOT_FILE.armbian-config-backup" ]
}

@test "CPU boot: preserves permissions and refuses a concurrent editor" {
	chmod 640 "$BOOT_FILE"
	exec {testlock}>"$BOOT_FILE.armbian-config.lock"
	flock "$testlock"
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	exec {testlock}>&-
	module_cpu_power persist schedutil 1008000
	[ "$(stat -c %a "$BOOT_FILE")" = 640 ]
	module_cpu_power restore-boot
	[ "$(stat -c %a "$BOOT_FILE")" = 640 ]
}

@test "CPU boot: failed backup preparation leaves original and cleans incomplete state" {
	cp() {
		[[ "${*: -1}" != */after ]] || return 1
		command cp "$@"
	}
	run module_cpu_power persist schedutil 1008000
	[ "$status" -ne 0 ]
	cmp "$BOOT_FILE" "$BOOT_FILE.original"
	[ ! -e "$BOOT_FILE.armbian-config-backup" ]
}
