#!/usr/bin/env bats

setup() {
	declare -gA module_options=()
	source "${BATS_TEST_DIRNAME}/../../tools/modules/system/module_usb_role.sh"
	command -v dtc >/dev/null && command -v fdtoverlay >/dev/null && command -v fdtget >/dev/null || skip 'device-tree-compiler is required'
	USB_ROOT="$BATS_TEST_TMPDIR/boot"; USB_DT="$BATS_TEST_TMPDIR/dt"; USB_CLASS="$BATS_TEST_TMPDIR/class"
	mkdir -p "$USB_ROOT/dtb/allwinner/overlay" "$USB_DT/soc/usb@5100000" "$USB_CLASS/udc/test-udc"
	_usb_role_boot_root() { echo "$USB_ROOT"; }
	_usb_role_dt_root() { echo "$USB_DT"; }
	_usb_role_class_root() { echo "$USB_CLASS"; }
	printf 'xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0' > "$USB_DT/compatible"
	printf 'peripheral\0' > "$USB_DT/soc/usb@5100000/dr_mode"
	printf 'okay\0' > "$USB_DT/soc/usb@5100000/status"
	printf 'not attached\n' > "$USB_CLASS/udc/test-udc/state"
	printf 'load armbianEnv.txt\nload ${overlay_prefix}-${overlay_file}.dtbo\n' > "$USB_ROOT/boot.scr"
	printf '# original\nfdtfile=allwinner/sun50i-h618-orangepi-zero2w.dtb\noverlay_prefix=sun50i-h616\nrootdev=UUID=test\noverlays=unrelated\n' > "$USB_ROOT/armbianEnv.txt"
	chmod 640 "$USB_ROOT/armbianEnv.txt"
	cp -p "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/original"
	cat > "$BATS_TEST_TMPDIR/base.dts" <<'DTS'
/dts-v1/;
/ { compatible = "xunlong,orangepi-zero2w", "allwinner,sun50i-h618";
 soc {
  usbotg: usb@5100000 { status = "okay"; dr_mode = "peripheral"; };
  usbphy: phy@5100400 { status = "okay"; };
  ehci0: usb@5101000 { status = "disabled"; };
  ohci0: usb@5101400 { status = "disabled"; };
  ehci1: usb@5200000 { status = "okay"; };
  ohci1: usb@5200400 { status = "okay"; };
 };
};
DTS
	cat > "$BATS_TEST_TMPDIR/host.dts" <<'DTS'
/dts-v1/; /plugin/;
&usbotg { dr_mode = "host"; status = "okay"; };
&usbphy { status = "okay"; };
&ehci0 { status = "okay"; };
&ohci0 { status = "okay"; };
DTS
	cat > "$BATS_TEST_TMPDIR/unrelated.dts" <<'DTS'
/dts-v1/; /plugin/;
&{/} { test-property = "unchanged"; };
DTS
	dtc -q -@ -I dts -O dtb -o "$USB_ROOT/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb" "$BATS_TEST_TMPDIR/base.dts"
	dtc -q -@ -I dts -O dtb -o "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-usb0-host.dtbo" "$BATS_TEST_TMPDIR/host.dts"
	dtc -q -@ -I dts -O dtb -o "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-unrelated.dtbo" "$BATS_TEST_TMPDIR/unrelated.dts"
}

@test 'USB: status separates live DT, UDC and boot environment without writes' {
	run module_usb_role status
	[ "$status" -eq 0 ]
	[[ "$output" == *'peripheral'* && "$output" == *'not attached'* && "$output" == *'not a gadget function'* ]]
	cmp "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/original"
	[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
}
@test 'USB: host composes real overlays, preserves others, permissions and exact rollback' {
	run module_usb_role boot host
	[ "$status" -eq 0 ]
	grep -qx 'overlays=unrelated usb0-host' "$USB_ROOT/armbianEnv.txt"
	grep -qx 'rootdev=UUID=test' "$USB_ROOT/armbianEnv.txt"
	[ "$(stat -c %a "$USB_ROOT/armbianEnv.txt")" = 640 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt.usb-role-backup/before"
	[ "$(tr -d '\0' < "$USB_DT/soc/usb@5100000/dr_mode")" = peripheral ]
	run module_usb_role restore
	[ "$status" -eq 0 ]
	cmp "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/original"
	[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
}
@test 'USB: device removes only usb0-host from boot config' {
	sed -i 's/overlays=unrelated/overlays=usb0-host unrelated/' "$USB_ROOT/armbianEnv.txt"
	run module_usb_role boot device
	[ "$status" -eq 0 ]
	grep -qx 'overlays=unrelated' "$USB_ROOT/armbianEnv.txt"
	! grep -q usb0-host "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: reject unknown role and board before replacing config' {
	for role in auto otg client none '../host' ''; do
		run module_usb_role boot "$role"
		[ "$status" -ne 0 ]
	done
	printf 'another,board\0' > "$USB_DT/compatible"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/original"
	[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
}
@test 'USB: refuse duplicate keys, custom paths, shell-like names and parameters' {
	for line in 'overlays=unrelated' 'param_usb0=host' 'user_overlays=custom' 'overlaydir=other' 'fdtfile=../../evil'; do
		cp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
		printf '%s\n' "$line" >> "$USB_ROOT/armbianEnv.txt"
		cp "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/expected"
		run module_usb_role boot host
		[ "$status" -ne 0 ]
		cmp "$USB_ROOT/expected" "$USB_ROOT/armbianEnv.txt"
		[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
	done
	cp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
	sed -i 's/overlays=unrelated/overlays=$(touch bad)/' "$USB_ROOT/armbianEnv.txt"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
}
@test 'USB: missing overlay and invalid DT never publish boot environment' {
	rm "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-usb0-host.dtbo"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
	printf invalid > "$USB_ROOT/dtb/allwinner/sun50i-h618-orangepi-zero2w.dtb"
	run module_usb_role boot device
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: conflicting composed DT is rejected for device mode' {
	cp "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-usb0-host.dtbo" "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-unrelated.dtbo"
	run module_usb_role boot device
	[ "$status" -ne 0 ]
	[[ "$output" == *'does not provide'* ]]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: reject host overlay that leaves OHCI0 disabled' {
	sed -i '/&ohci0/d' "$BATS_TEST_TMPDIR/host.dts"
	dtc -q -@ -I dts -O dtb -o "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-usb0-host.dtbo" "$BATS_TEST_TMPDIR/host.dts"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	[[ "$output" == *'Conflicting USB0'* ]]
}
@test 'USB: external edits prevent automatic restore and retain backup' {
	module_usb_role boot host
	printf 'verbosity=7\n' >> "$USB_ROOT/armbianEnv.txt"
	cp "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/expected"
	run module_usb_role restore
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/expected" "$USB_ROOT/armbianEnv.txt"
	[ -f "$USB_ROOT/armbianEnv.txt.usb-role-backup/before" ]
}
@test 'USB: pending backup prevents another save' {
	module_usb_role boot host
	cp "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/expected"
	run module_usb_role boot device
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/expected" "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: environment, lock and backup symlinks are refused' {
	mv "$USB_ROOT/armbianEnv.txt" "$USB_ROOT/target"
	ln -s target "$USB_ROOT/armbianEnv.txt"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	rm "$USB_ROOT/armbianEnv.txt"
	mv "$USB_ROOT/target" "$USB_ROOT/armbianEnv.txt"
	ln -s target "$USB_ROOT/armbianEnv.txt.usb-role.lock"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	rm "$USB_ROOT/armbianEnv.txt.usb-role.lock"
	ln -s nowhere "$USB_ROOT/armbianEnv.txt.usb-role-backup"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: incomplete preparation cleans up and rename failure stays recoverable' {
	cp() { return 1; }
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
	unset -f cp
	mv() { return 1; }
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
	[ -f "$USB_ROOT/armbianEnv.txt.usb-role-backup/after" ]
	unset -f mv
	run module_usb_role restore
	[ "$status" -eq 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: lock contention prevents changes' {
	exec {usb_lock}>"$USB_ROOT/armbianEnv.txt.usb-role.lock"
	flock "$usb_lock"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
	exec {usb_lock}>&-
}
@test 'USB: unsupported boot path is refused' {
	mkdir -p "$USB_ROOT/extlinux"
	touch "$USB_ROOT/extlinux/extlinux.conf"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	rm "$USB_ROOT/extlinux/extlinux.conf"
	printf unknown > "$USB_ROOT/boot.scr"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
}
@test 'USB: cancelling menu or confirmation leaves config untouched' {
	dialog_menu() { return 1; }
	run module_usb_role select
	[ "$status" -eq 0 ]
	dialog_menu() { echo host; }
	dialog_yesno() { return 1; }
	run module_usb_role select
	[ "$status" -eq 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
	[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
}
@test 'USB: no-op preserves file and leaves no pending backup' {
	run module_usb_role boot device
	[ "$status" -eq 0 ]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
	[ ! -e "$USB_ROOT/armbianEnv.txt.usb-role-backup" ]
}
@test 'USB: composed overlays may not change USB1 host controllers' {
	printf '\n&ehci1 { status = "disabled"; };\n' >> "$BATS_TEST_TMPDIR/host.dts"
	dtc -q -@ -I dts -O dtb -o "$USB_ROOT/dtb/allwinner/overlay/sun50i-h616-usb0-host.dtbo" "$BATS_TEST_TMPDIR/host.dts"
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	[[ "$output" == *'changes USB1'* ]]
	cmp "$USB_ROOT/original" "$USB_ROOT/armbianEnv.txt"
}
@test 'USB: manual edits during preparation prevent publication' {
	eval "$(declare -f _usb_role_prepare | sed '1s/_usb_role_prepare/_usb_role_prepare_original/')"
	_usb_role_prepare() {
		_usb_role_prepare_original "$@" || return 1
		printf 'verbosity=7\n' >> "$USB_ROOT/armbianEnv.txt"
	}
	run module_usb_role boot host
	[ "$status" -ne 0 ]
	[[ "$output" == *'changed during validation'* ]]
	grep -qx 'verbosity=7' "$USB_ROOT/armbianEnv.txt"
	grep -qx 'overlays=unrelated' "$USB_ROOT/armbianEnv.txt"
}
