module_options+=(
	["module_screen_settings,author"]="@shipmarty43"
	["module_screen_settings,maintainer"]="@shipmarty43"
	["module_screen_settings,feature"]="module_screen_settings"
	["module_screen_settings,desc"]="Inspect DRM outputs and open the desktop's display settings"
	["module_screen_settings,example"]="select status sessions open help"
	["module_screen_settings,status"]="Preview"
	["module_screen_settings,group"]="System"
	["module_screen_settings,help_open"]="Open native display settings in a local graphical session: open SESSION"
)

function _screen_drm_root() { printf '%s\n' /sys/class/drm; }

function _screen_status() {
	local path name field found=false
	for path in "$(_screen_drm_root)"/card*-*; do
		name="${path##*/}"
		[[ "$name" =~ ^card[0-9]+-.+$ && -r "$path/status" ]] || continue
		found=true
		printf '%s\n' "$name"
		for field in status enabled modes; do
			if [[ -r "$path/$field" ]]; then
				printf '  %s:\n' "$field"
				sed 's/^/    /' "$path/$field" || return 1
			fi
		done
	done
	if [[ "$found" == false ]]; then echo 'No DRM connectors exposed by the running kernel.'; fi
	printf '%s\n' 'Modes are advertised choices, not the current mode. A connector does not prove a working picture.'
	printf '%s\n' 'CVBS requires a working TV encoder driver and device tree; a settings panel cannot add missing hardware support.'
}

# Read logind properties as data, never as shell assignments.
function _screen_session() {
	local session="${1:-}" properties key value name='' uid='' type='' active='' remote='' class='' desktop=''
	[[ "$session" =~ ^[a-zA-Z0-9_-]+$ ]] || return 1
	properties=$(loginctl show-session "$session" --no-pager \
		-p Name -p User -p Type -p Active -p Remote -p Class -p Desktop) || return 1
	while IFS='=' read -r key value; do
		case "$key" in
			Name) name="$value" ;;
			User) uid="$value" ;;
			Type) type="$value" ;;
			Active) active="$value" ;;
			Remote) remote="$value" ;;
			Class) class="$value" ;;
			Desktop) desktop="$value" ;;
		esac
	done <<< "$properties"
	[[ "$uid" =~ ^[0-9]+$ && "$uid" != 0 && "$name" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]] || return 1
	[[ "$type" == x11 || "$type" == wayland ]] || return 1
	[[ "$active" == yes && "$remote" == no && "$class" == user ]] || return 1
	[[ "$desktop" =~ ^[a-zA-Z0-9_:.-]+$ ]] || desktop=unknown
	printf '%s %s %s %s %s\n' "$session" "$name" "$uid" "$type" "$desktop"
}

function _screen_sessions() {
	local rows session rest
	rows=$(loginctl list-sessions --no-legend --no-pager) || return 1
	while read -r session rest; do
		[[ -n "$session" ]] || continue
		_screen_session "$session" || continue
	done <<< "$rows"
}

function _screen_panel() {
	case "${1,,}" in
		*gnome* | ubuntu*) printf '%s\n' /usr/bin/gnome-control-center display ;;
		*kde* | *plasma*) printf '%s\n' /usr/bin/systemsettings kcm_kscreen ;;
		*xfce*) printf '%s\n' /usr/bin/xfce4-display-settings ;;
		*cinnamon*) printf '%s\n' /usr/bin/cinnamon-settings display ;;
		*mate*) printf '%s\n' /usr/bin/mate-display-properties ;;
		*lxqt*) printf '%s\n' /usr/bin/lxqt-config-monitor ;;
		*)
			echo 'No supported native panel for this desktop. Open display settings from the desktop itself.' >&2
			return 1
			;;
	esac
}

function _screen_program_available() { [[ -x "$1" ]]; }
function _screen_user_environment() { systemctl --user --machine="$1@.host" show-environment; }
function _screen_launch() {
	local user="$1"
	shift
	systemd-run --user --machine="$user@.host" --collect --property=Type=exec -- "$@"
}

function _screen_open() {
	local row session name uid type desktop env panel rows _other_session _other_name other_uid rest count=0
	local -a command_args
	row=$(_screen_session "${1:-}") || {
		echo 'Select an active local non-root graphical user session.' >&2
		return 1
	}
	read -r session name uid type desktop <<< "$row"
	rows=$(_screen_sessions) || return 1
	while read -r _other_session _other_name other_uid rest; do
		[[ "$other_uid" == "$uid" ]] && count=$((count + 1))
	done <<< "$rows"
	[[ "$count" == 1 ]] || {
		echo 'Ambiguous graphical sessions for this user; open the panel from the desktop.' >&2
		return 1
	}
	panel=$(_screen_panel "$desktop") || return 1
	mapfile -t command_args <<< "$panel"
	_screen_program_available "${command_args[0]}" || {
		echo 'The native display panel is not installed.' >&2
		return 1
	}
	env=$(_screen_user_environment "$name") || {
		echo 'Cannot contact the graphical user manager. Open the panel from the desktop.' >&2
		return 1
	}
	if [[ "$type" == wayland ]]; then
		grep -q '^WAYLAND_DISPLAY=.' <<< "$env" || {
			echo 'User manager has no Wayland display environment.' >&2
			return 1
		}
	else
		grep -q '^DISPLAY=.' <<< "$env" || {
			echo 'User manager has no X11 display environment.' >&2
			return 1
		}
	fi
	_screen_launch "$name" "${command_args[@]}" || return 1
	printf 'Launch request accepted for %s (%s). Make and confirm changes in the desktop panel.\n' "$name" "$type"
}

function _screen_select() {
	local action rows session name uid type desktop selected output
	local -a choices=()
	action=$(dialog_menu 'Displays' 'Inspect outputs or open settings in a local desktop session.' 18 78 3 -- \
		status 'DRM connector status and advertised modes' settings 'Native resolution, layout, rotation and scaling controls') || return 0
	case "$action" in
		status)
			output=$(_screen_status) || return 1
			dialog_msgbox 'DRM outputs' "$output" 24 86
			;;
		settings)
			rows=$(_screen_sessions) || {
				dialog_msgbox 'Displays' 'Unable to query logind sessions.'
				return 1
			}
			while read -r session name uid type desktop; do
				[[ -n "$session" ]] && choices+=("$session" "$name: $desktop ($type)")
			done <<< "$rows"
			if ((${#choices[@]} == 0)); then
				dialog_msgbox 'Displays' 'Log in to a local desktop first. SSH alone has no display session.'
				return 0
			fi
			selected=$(dialog_menu 'Display session' 'Choose the desktop receiving the settings window.' 18 78 8 -- "${choices[@]}") || return 0
			[[ -n "$selected" ]] || return 0
			if output=$(_screen_open "$selected" 2>&1); then dialog_msgbox 'Display settings' "$output"; else
				dialog_msgbox 'Display settings unavailable' "$output"
				return 1
			fi
			;;
		'') return 0 ;;
		*) return 1 ;;
	esac
}

function module_screen_settings() {
	case "${1:-help}" in
		status) _screen_status ;;
		sessions) _screen_sessions ;;
		open) _screen_open "${2:-}" ;;
		select) _screen_select ;;
		help) echo 'module_screen_settings status|sessions|open SESSION|select' ;;
		*) return 1 ;;
	esac
}
