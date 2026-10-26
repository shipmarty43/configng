module_options+=(
	["module_display_manager,author"]="@shipmarty43"
	["module_display_manager,maintainer"]="@shipmarty43"
	["module_display_manager,feature"]="module_display_manager"
	["module_display_manager,desc"]="Inspect and reconfigure an installed display manager"
	["module_display_manager,example"]="select status installed reconfigure help"
	["module_display_manager,status"]="Preview"
	["module_display_manager,group"]="System"
	["module_display_manager,help_reconfigure"]="Run the package's interactive configuration: reconfigure PACKAGE --confirm-session-interruption"
)

function _display_manager_default_file() { printf '%s\n' /etc/X11/default-display-manager; }
function _display_manager_supported() {
	case "${1:-}" in lightdm | gdm3 | sddm) return 0 ;; *) return 1 ;; esac
}
function _display_manager_installed() {
	local package state
	for package in lightdm gdm3 sddm; do
		state=$(dpkg-query -W -f='${Status}' "$package" 2> /dev/null) || continue
		[[ "$state" == 'install ok installed' ]] && printf '%s\n' "$package"
	done
	return 0
}

function _display_manager_status() {
	local path value
	path=$(_display_manager_default_file)
	if [[ -r "$path" ]]; then value=$(cat "$path") || return 1; else value='not configured'; fi
	printf 'Configured display manager: %s\n' "$value"
	printf 'Installed supported packages:\n'
	_display_manager_installed || return 1
	printf 'Systemd state (may differ from the configured default):\n'
	systemctl show display-manager.service --no-pager -p Id -p LoadState -p ActiveState -p FragmentPath || return 1
}

function _display_manager_reconfigure() {
	local package="${1:-}" confirmed="${2:-}" installed
	_display_manager_supported "$package" || {
		echo 'Unsupported display manager package.' >&2
		return 1
	}
	installed=$(_display_manager_installed) || return 1
	grep -Fxq "$package" <<< "$installed" || {
		echo 'The requested display manager is not installed.' >&2
		return 1
	}
	[[ "$confirmed" == --confirm-session-interruption ]] || {
		echo 'Package configuration may restart the login service and end graphical sessions. Save work; explicitly pass --confirm-session-interruption.' >&2
		return 1
	}
	command -v dpkg-reconfigure > /dev/null || {
		echo 'dpkg-reconfigure is unavailable.' >&2
		return 1
	}
	# Let Debian/Ubuntu packages manage debconf and their service links together.
	# Do not hand-edit the service alias or claim this is a next-boot-only operation.
	dpkg-reconfigure --frontend=dialog "$package" || return 1
	echo 'Package configuration completed. Current default and service state:'
	_display_manager_status
}

function _display_manager_select() {
	local action installed package selected output
	local -a choices=()
	action=$(dialog_menu 'Display manager' 'Manage the graphical login service.' 18 78 3 -- \
		status 'Configured default and running service' configure 'Choose default DM using package configuration') || return 0
	case "$action" in
		status)
			if output=$(_display_manager_status 2>&1); then dialog_msgbox 'Display manager' "$output"; else
				dialog_msgbox 'Display manager query failed' "$output"
				return 1
			fi
			;;
		configure)
			installed=$(_display_manager_installed) || return 1
			while IFS= read -r package; do [[ -n "$package" ]] && choices+=("$package" 'Installed package'); done <<< "$installed"
			if ((${#choices[@]} == 0)); then
				dialog_msgbox 'Display manager' 'No supported DM installed. Install a desktop first.'
				return 0
			fi
			selected=$(dialog_menu 'Package configuration' 'Select a package to open the default-DM chooser.' 18 78 5 -- "${choices[@]}") || return 0
			[[ -n "$selected" ]] || return 0
			dialog_yesno 'Save your work' 'Package scripts may restart the graphical login service and end desktop sessions. Continue from this terminal?' 'Continue' 'Cancel' 12 78 --defaultno || return 0
			# Keep the terminal attached to the interactive debconf dialog.
			_display_manager_reconfigure "$selected" --confirm-session-interruption || return 1
			;;
		'') return 0 ;;
		*) return 1 ;;
	esac
}

function module_display_manager() {
	case "${1:-help}" in
		status) _display_manager_status ;;
		installed) _display_manager_installed ;;
		reconfigure) _display_manager_reconfigure "${2:-}" "${3:-}" ;;
		select) _display_manager_select ;;
		help) echo 'module_display_manager status|installed|select|reconfigure PACKAGE --confirm-session-interruption' ;;
		*) return 1 ;;
	esac
}
