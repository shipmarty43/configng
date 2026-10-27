#!/usr/bin/env bats
setup() {
	declare -gA module_options=()
	source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_ups_dfr0528.sh"
	source "$BATS_TEST_DIRNAME/../../tools/modules/system/module_devicetree_overlays.sh"
	command -v dtc >/dev/null && command -v fdtoverlay >/dev/null || skip 'dtc required'
	UPS_ROOT="$BATS_TEST_TMPDIR/boot"; UPS_DT="$BATS_TEST_TMPDIR/dt"; UPS_CLASS="$BATS_TEST_TMPDIR/class"
	mkdir -p "$UPS_ROOT/dtb/allwinner/overlay" "$UPS_ROOT/overlay-user" "$UPS_DT" "$UPS_CLASS"
	_ups_dfr_boot() { echo "$UPS_ROOT"; }
	_ups_dfr_dt() { echo "$UPS_DT"; }
	_ups_dfr_supplies() { echo "$UPS_CLASS"; }
	_ups_dfr_driver() { return 0; }
	printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$UPS_DT/compatible"
	printf 'load armbianEnv.txt\nload ${prefix}overlay-user/${overlay_file}.dtbo\n' > "$UPS_ROOT/boot.scr"
	printf '# original\noverlay_prefix=sun50i-h616\noverlays=unrelated\nuser_overlays=existing\nrootdev=UUID=test\n' > "$UPS_ROOT/armbianEnv.txt"
	chmod 640 "$UPS_ROOT/armbianEnv.txt"
	cp -p "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
	cat > "$BATS_TEST_TMPDIR/base.dts" <<'DTS'
/dts-v1/;
/ { compatible="xunlong,orangepi-zero2w", "allwinner,sun50i-h618";
 soc { pinctrl@300b000 { i2c1_pi_pins: i2c1-pi-pins { pins="PI7", "PI8"; function="i2c1"; }; };
 i2c1: i2c@5002400 { status="disabled"; #address-cells=<1>; #size-cells=<0>; }; };
};
DTS
	cat > "$BATS_TEST_TMPDIR/i2c.dts" <<'DTS'
/dts-v1/; /plugin/;
&i2c1 { status="okay"; pinctrl-0=<&i2c1_pi_pins>; pinctrl-names="default"; };
DTS
	cat > "$BATS_TEST_TMPDIR/unrelated.dts" <<'DTS'
/dts-v1/; /plugin/;
&{/} { preserved="yes"; };
DTS
	dtc -q -@ -I dts -O dtb -o "$UPS_ROOT/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb" "$BATS_TEST_TMPDIR/base.dts"
	dtc -q -@ -I dts -O dtb -o "$UPS_ROOT/dtb/allwinner/overlay/sun50i-h616-i2c1-pi.dtbo" "$BATS_TEST_TMPDIR/i2c.dts"
	dtc -q -@ -I dts -O dtb -o "$UPS_ROOT/dtb/allwinner/overlay/sun50i-h616-unrelated.dtbo" "$BATS_TEST_TMPDIR/unrelated.dts"
	cp "$UPS_ROOT/dtb/allwinner/overlay/sun50i-h616-unrelated.dtbo" "$UPS_ROOT/overlay-user/existing.dtbo"
	dtc -q -@ -I dts -O dtb -o "$UPS_ROOT/overlay-user/zero2w-dfr0528.dtbo" "$BATS_TEST_DIRNAME/../../hardware/dfrobot-ups/zero2w-dfr0528.dts"
}
@test 'UPS: enable composes DT, adds I2C dependency, preserves other overlays and permissions' {
	run module_devicetree_overlays ups enable
	[ "$status" -eq 0 ]
	grep -qx 'overlays=unrelated i2c1-pi' "$UPS_ROOT/armbianEnv.txt"
	grep -qx 'user_overlays=existing zero2w-dfr0528' "$UPS_ROOT/armbianEnv.txt"
	grep -qx 'rootdev=UUID=test' "$UPS_ROOT/armbianEnv.txt"
	[ "$(stat -c %a "$UPS_ROOT/armbianEnv.txt")" = 640 ]
	cmp "$UPS_ROOT/original" "$UPS_ROOT"/armbianEnv.txt.ups-backups/change.*/before
	cp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/enabled"
	run module_ups_dfr0528 enable
	[ "$status" -eq 0 ]; [[ "$output" == *'no change'* ]]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/enabled"
}
@test 'UPS: disable removes only UPS and retains shared I2C, including when driver/DTBO is missing' {
	module_ups_dfr0528 enable
	rm "$UPS_ROOT/overlay-user/zero2w-dfr0528.dtbo"
	_ups_dfr_driver() { return 1; }
	run module_devicetree_overlays ups disable
	[ "$status" -eq 0 ]
	grep -qx 'overlays=unrelated i2c1-pi' "$UPS_ROOT/armbianEnv.txt"
	grep -qx 'user_overlays=existing' "$UPS_ROOT/armbianEnv.txt"
}
@test 'UPS: reject missing driver before changing boot config' {
	_ups_dfr_driver() { return 1; }
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]; [[ "$output" == *DKMS* ]]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
}
@test 'UPS: reject corrupt or missing overlays atomically' {
	printf 'invalid DTBO' > "$UPS_ROOT/overlay-user/zero2w-dfr0528.dtbo"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
	rm "$UPS_ROOT/overlay-user/zero2w-dfr0528.dtbo"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
}
@test 'UPS: reject duplicate keys, shell-like names and DT fixup parameters' {
	for addition in 'user_overlays=other' 'param_i2c=1' 'user_overlays=../bad' 'fdtfile=wrong.dtb'; do
		cp "$UPS_ROOT/original" "$UPS_ROOT/armbianEnv.txt"
		printf '%s\n' "$addition" >> "$UPS_ROOT/armbianEnv.txt"
		cp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/before-reject"
		run module_ups_dfr0528 enable
		[ "$status" -ne 0 ]
		cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/before-reject"
	done
}
@test 'UPS: reject conflicting overlay that disables I2C after stock overlays' {
	printf '/dts-v1/; /plugin/; &i2c1 {status="disabled";};\n' > "$BATS_TEST_TMPDIR/conflict.dts"
	dtc -q -@ -I dts -O dtb -o "$UPS_ROOT/overlay-user/existing.dtbo" "$BATS_TEST_TMPDIR/conflict.dts"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]; [[ "$output" == *'expected UPS'* ]]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
}
@test 'UPS: reject wrong board, unsupported boot route and symlink config' {
	printf 'other,board\0' > "$UPS_DT/compatible"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
	printf 'xunlong,orangepi-zero2w\0' > "$UPS_DT/compatible"
	mkdir -p "$UPS_ROOT/extlinux"; touch "$UPS_ROOT/extlinux/extlinux.conf"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
	rm "$UPS_ROOT/extlinux/extlinux.conf" "$UPS_ROOT/armbianEnv.txt"
	ln -s "$UPS_ROOT/original" "$UPS_ROOT/armbianEnv.txt"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
}
@test 'UPS: stock manager blocks I2C removal but permits unrelated changes and preserves user overlays' {
	module_ups_dfr0528 enable
	cp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/enabled"
	run _dt_overlays_write_config "$UPS_ROOT/armbianEnv.txt" false unrelated
	[ "$status" -ne 0 ]; [[ "$output" == *'Cannot disable i2c1-pi'* ]]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/enabled"
	run _dt_overlays_write_config "$UPS_ROOT/armbianEnv.txt" false 'i2c1-pi'
	[ "$status" -eq 0 ]
	grep -qx 'user_overlays=existing zero2w-dfr0528' "$UPS_ROOT/armbianEnv.txt"
}
@test 'UPS: status distinguishes boot selection, driver and live telemetry' {
	mkdir "$UPS_CLASS/dfr0528-test"
	printf '61\n' > "$UPS_CLASS/dfr0528-test/capacity"
	printf 'Unknown\n' > "$UPS_CLASS/dfr0528-test/status"
	run module_devicetree_overlays ups status
	[ "$status" -eq 0 ]; [[ "$output" == *'Live capacity: 61'* && "$output" == *'Live status: Unknown'* ]]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
}
@test 'UPS: overlay TUI routes UPS action and cancellation without changes' {
	dialog_menu() { echo ups; }
	module_ups_dfr0528() { echo "UPS submenu: $1"; }
	run module_devicetree_overlays edit
	[ "$status" -eq 0 ]; [[ "$output" == *'UPS submenu: select'* ]]
	dialog_menu() { return 1; }
	run module_devicetree_overlays edit
	[ "$status" -eq 0 ]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
}
@test 'UPS: disabled UPS node in another overlay is rejected' {
	printf '/dts-v1/; /plugin/; &i2c1 {ups@10 {status="disabled";};};\n' > "$BATS_TEST_TMPDIR/conflict.dts"
	dtc -q -@ -I dts -O dtb -o "$UPS_ROOT/overlay-user/existing.dtbo" "$BATS_TEST_TMPDIR/conflict.dts"
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
}
@test 'UPS: stock writer preserves mode and refuses an unsafe backup path' {
	run _dt_overlays_write_config "$UPS_ROOT/armbianEnv.txt" false 'unrelated i2c1-pi'
	[ "$status" -eq 0 ]
	[ "$(stat -c %a "$UPS_ROOT/armbianEnv.txt")" = 640 ]
	cmp "$UPS_ROOT/original" "$UPS_ROOT/armbianEnv.txt.bak"
	cp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/before-reject"
	rm "$UPS_ROOT/armbianEnv.txt.bak"
	ln -s "$UPS_ROOT/original" "$UPS_ROOT/armbianEnv.txt.bak"
	run _dt_overlays_write_config "$UPS_ROOT/armbianEnv.txt" false unrelated
	[ "$status" -ne 0 ]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/before-reject"
}
@test 'UPS: generic show includes user overlays and other boards retain stock TUI' {
	_dt_overlays_resolve_paths() { overlayconf="$UPS_ROOT/armbianEnv.txt"; is_pi=false; }
	run module_devicetree_overlays show
	[ "$status" -eq 0 ]; [[ "$output" == *'user:existing'* ]]
	_ups_dfr_board() { return 1; }
	_dt_overlays_edit() { echo 'stock editor'; }
	run module_devicetree_overlays edit
	[ "$status" -eq 0 ]; [[ "$output" == 'stock editor' ]]
}
@test 'UPS: failed rename leaves original config and recoverable before/after backup' {
	mv() { return 1; }
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]
	cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/original"
	cmp "$UPS_ROOT/original" "$UPS_ROOT"/armbianEnv.txt.ups-backups/change.*/before
}
@test 'UPS: concurrent manual edit is not overwritten' {
	eval "$(declare -f _ups_dfr_prepare | sed '1s/_ups_dfr_prepare/_original_ups_prepare/')"
	_ups_dfr_prepare() { _original_ups_prepare "$@" && printf '# external edit\n' >> "$UPS_ROOT/armbianEnv.txt"; }
	run module_ups_dfr0528 enable
	[ "$status" -ne 0 ]; [[ "$output" == *'changed concurrently'* ]]
	grep -qx '# external edit' "$UPS_ROOT/armbianEnv.txt"
	grep -qx 'overlays=unrelated' "$UPS_ROOT/armbianEnv.txt"
}
@test 'UPS: traversal and shell-like overlay tokens are rejected without executing them' {
	for token in '../bad' '$(false)' 'bad;false'; do
		sed "s|user_overlays=existing|user_overlays=$token|" "$UPS_ROOT/original" > "$UPS_ROOT/armbianEnv.txt"
		cp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/before-reject"
		run module_ups_dfr0528 enable
		[ "$status" -ne 0 ]
		cmp "$UPS_ROOT/armbianEnv.txt" "$UPS_ROOT/before-reject"
	done
}
@test 'UPS: shared writer retains Raspberry Pi managed-block format' {
	printf '# retained\narm_64bit=1\n# Armbian config\ndtoverlay=old\n' > "$UPS_ROOT/pi-config.txt"
	run _dt_overlays_write_config "$UPS_ROOT/pi-config.txt" true $'uart3\nspi-spidev'
	[ "$status" -eq 0 ]
	grep -qx 'arm_64bit=1' "$UPS_ROOT/pi-config.txt"
	grep -qx 'dtoverlay=uart3' "$UPS_ROOT/pi-config.txt"
	grep -qx 'dtoverlay=spi-spidev' "$UPS_ROOT/pi-config.txt"
	! grep -qx 'dtoverlay=old' "$UPS_ROOT/pi-config.txt"
}
@test 'UPS: dependency guard uses complete names and releases I2C after UPS disable' {
	module_ups_dfr0528 enable
	run _dt_overlays_write_config "$UPS_ROOT/armbianEnv.txt" false 'i2c1-pi-extra'
	[ "$status" -ne 0 ]
	module_ups_dfr0528 disable
	run _dt_overlays_write_config "$UPS_ROOT/armbianEnv.txt" false unrelated
	[ "$status" -eq 0 ]
	grep -qx 'overlays=unrelated' "$UPS_ROOT/armbianEnv.txt"
}
