#!/usr/bin/env bats

setup() {
	declare -gA module_options=()
	source "${BATS_TEST_DIRNAME}/../../tools/modules/desktops/module_screen_settings.sh"
	source "${BATS_TEST_DIRNAME}/../../tools/modules/desktops/module_display_manager.sh"
	DRM_FIXTURE="$BATS_TEST_TMPDIR/drm"
	DM_FIXTURE="$BATS_TEST_TMPDIR/default-display-manager"
	CALLS="$BATS_TEST_TMPDIR/calls"
	mkdir -p "$DRM_FIXTURE/card0-HDMI-A-1"
	printf 'connected\n' >"$DRM_FIXTURE/card0-HDMI-A-1/status"
	printf 'enabled\n' >"$DRM_FIXTURE/card0-HDMI-A-1/enabled"
	printf '1920x1080\n1280x720\n' >"$DRM_FIXTURE/card0-HDMI-A-1/modes"
	printf '/usr/sbin/lightdm\n' >"$DM_FIXTURE"
	_screen_drm_root() { echo "$DRM_FIXTURE"; }
	_display_manager_default_file() { echo "$DM_FIXTURE"; }
	TYPE=wayland DESKTOP=GNOME ACTIVE=yes REMOTE=no CLASS=user SESSION_UID=1000 SESSION_NAME=alice
	loginctl() {
		case "$1" in
		list-sessions)
			printf 'c1 1000 alice seat0 tty2\n'
			[[ "${DUPLICATE:-no}" == no ]] || printf 'c2 1000 alice seat1 tty3\n'
			;;
		show-session)
			[[ "$2" == c1 || "$2" == c2 ]] || return 1
			printf 'Name=%s\nUser=%s\nType=%s\nActive=%s\nRemote=%s\nClass=%s\nDesktop=%s\n' "$SESSION_NAME" "$SESSION_UID" "$TYPE" "$ACTIVE" "$REMOTE" "$CLASS" "$DESKTOP"
			;;
		*) return 1 ;;
		esac
	}
	_screen_program_available() { return 0; }
	_screen_user_environment() { printf 'WAYLAND_DISPLAY=wayland-0\nDISPLAY=:0\n'; }
	systemd-run() { printf '%s\n' "$@" >"$CALLS"; }
	dpkg-query() {
		case "${*: -1}" in lightdm | sddm) printf 'install ok installed' ;; gdm3) printf 'deinstall ok config-files' ;; *) return 1 ;; esac
	}
	dpkg-reconfigure() { printf '%s\n' "$@" >"$CALLS"; }
	systemctl() { printf 'Id=lightdm.service\nActiveState=active\n'; }
}

@test "Displays: DRM modes are reported without claiming current mode or CVBS support" {
	run module_screen_settings status
	[ "$status" -eq 0 ]
	[[ "$output" == *card0-HDMI-A-1* && "$output" == *1920x1080* && "$output" == *'not the current mode'* ]]
	[ "$(cat "$DRM_FIXTURE/card0-HDMI-A-1/status")" = connected ]
	[ ! -e "$CALLS" ]
}

@test "Displays: headless kernel is a useful diagnostic result" {
	rm -r "$DRM_FIXTURE"
	run module_screen_settings status
	[ "$status" -eq 0 ]
	[[ "$output" == *'No DRM connectors'* ]]
}

@test "Displays: launch GNOME settings in the user's manager with fixed arguments" {
	run module_screen_settings open c1
	[ "$status" -eq 0 ]
	[ "$(cat "$CALLS")" = $'--user\n--machine=alice@.host\n--collect\n--property=Type=exec\n--\n/usr/bin/gnome-control-center\ndisplay' ]
}

@test "Displays: X11 XFCE uses its own settings panel" {
	TYPE=x11 DESKTOP=XFCE
	run module_screen_settings open c1
	[ "$status" -eq 0 ]
	[[ "$(cat "$CALLS")" == *'/usr/bin/xfce4-display-settings' ]]
}

@test "Displays: reject remote, inactive, greeter, root and non-graphical sessions" {
	REMOTE=yes
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	REMOTE=no ACTIVE=no
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	ACTIVE=yes CLASS=greeter
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	CLASS=user SESSION_UID=0
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	SESSION_UID=1000 TYPE=tty
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	[ ! -e "$CALLS" ]
}

@test "Displays: reject malformed session and username data without executing it" {
	run module_screen_settings open '../c1'
	[ "$status" -ne 0 ]
	SESSION_NAME='$(touch injected)'
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	[ ! -e "$CALLS" ]
}

@test "Displays: refuse ambiguous sessions rather than target the wrong display" {
	DUPLICATE=yes
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	[[ "$output" == *Ambiguous* ]]
	[ ! -e "$CALLS" ]
}

@test "Displays: absent session environment never falls back to root's display" {
	_screen_user_environment() { printf 'HOME=/home/alice\n'; }
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	[[ "$output" == *'no Wayland display'* ]]
	[ ! -e "$CALLS" ]
}

@test "Displays: unsupported desktop or missing executable is reported" {
	DESKTOP=unknown
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	DESKTOP=GNOME
	_screen_program_available() { return 1; }
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	[ ! -e "$CALLS" ]
}

@test "Displays: user manager and process startup failures propagate" {
	systemd-run() { return 17; }
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
	_screen_user_environment() { return 1; }
	run module_screen_settings open c1
	[ "$status" -ne 0 ]
}

@test "Displays: menu cancellation never launches a panel" {
	dialog_menu() { return 1; }
	run module_screen_settings select
	[ "$status" -eq 0 ]
	[ ! -e "$CALLS" ]
}

@test "DM: installed list excludes removed packages and status keeps configured and live state separate" {
	run module_display_manager installed
	[ "$status" -eq 0 ]
	[ "$output" = $'lightdm\nsddm' ]
	run module_display_manager status
	[ "$status" -eq 0 ]
	[[ "$output" == *'/usr/sbin/lightdm'* && "$output" == *'Id=lightdm.service'* ]]
	[ ! -e "$CALLS" ]
}

@test "DM: invalid, missing or unconfirmed package cannot trigger reconfiguration" {
	for package in '--help' '../lightdm' gdm3; do
		run module_display_manager reconfigure "$package" --confirm-session-interruption
		[ "$status" -ne 0 ]
	done
	run module_display_manager reconfigure lightdm
	[ "$status" -ne 0 ]
	[ ! -e "$CALLS" ]
}

@test "DM: explicit confirmation invokes native package dialog without editing the default directly" {
	run module_display_manager reconfigure sddm --confirm-session-interruption
	[ "$status" -eq 0 ]
	[ "$(cat "$CALLS")" = $'--frontend=dialog\nsddm' ]
	[ "$(cat "$DM_FIXTURE")" = /usr/sbin/lightdm ]
}

@test "DM: package configuration failure is not reported as success" {
	dpkg-reconfigure() { return 42; }
	run module_display_manager reconfigure lightdm --confirm-session-interruption
	[ "$status" -ne 0 ]
	[[ "$output" != *'configuration completed'* ]]
}

@test "DM: declining interruption confirmation does not reconfigure" {
	dialog_menu() { if [[ "$1" == 'Display manager' ]]; then echo configure; else echo lightdm; fi; }
	dialog_yesno() { return 1; }
	run module_display_manager select
	[ "$status" -eq 0 ]
	[ ! -e "$CALLS" ]
}

@test "Dialog: whiptail No and Escape survive successful clear" {
	source "${BATS_TEST_DIRNAME}/../../tools/modules/functions/module_dialog_ui.sh"
	DIALOG=whiptail BACKTITLE=test
	strip_color_codes() { printf '%s' "$1"; }
	clear() { return 0; }
	whiptail() { return "$ANSWER"; }
	for ANSWER in 1 255 0; do
		run dialog_yesno Title Question Continue Cancel 12 78 --defaultno
		[ "$status" -eq "$ANSWER" ]
	done
}
