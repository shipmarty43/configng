_mesh_mail_pick() {
    local title="$1" folder="$2" cli="$3" empty="$4" before=9223372036854775807 data key label choice
    local -a options
    while :; do
        if ! data=$("$cli" list "$folder" "$before" 2>&1); then
            dialog_msgbox "$title" "${data:-Mailbox unavailable.}" 10 68 >&2
            return 1
        fi
        if [[ -z "$data" ]]; then
            dialog_msgbox "$title" "$empty" 8 68 >&2
            return 1
        fi
        options=()
        while IFS=$'\t' read -r key label; do options+=("$key" "$label"); done <<< "$data"
        choice=$(dialog_menu "$title" 'Choose an entry' 19 78 11 -- "${options[@]}") || return 1
        case "$choice" in
            more-*) before=${choice#more-} ;;
            ''|*[!0-9]*) return 1 ;;
            *)
                # Return the selected id and its label from the same list snapshot.
                for ((key=0; key<${#options[@]}; key+=2)); do
                    if [[ "${options[key]}" == "$choice" ]]; then
                        printf '%s\t%s\n' "$choice" "${options[key+1]}"
                        return 0
                    fi
                done
                return 1 ;;
        esac
    done
}

_mesh_mail_read() (
    local folder="$1" title="$2" cli="$3" selected file
    selected=$(_mesh_mail_pick "$title" "$folder" "$cli" "No messages in this folder.") || return 0
    file=$(mktemp) || return 1
    trap 'rm -f -- "$file"' EXIT
    if ! "$cli" show "$folder" "${selected%%$'\t'*}" > "$file"; then
        dialog_msgbox "$title" 'Could not read the selected message.' 8 60
        return 1
    fi
    case "$DIALOG" in
        dialog) dialog --title "$title" --textbox "$file" 20 76 ;;
        whiptail) whiptail --title "$title" --scrolltext --textbox "$file" 20 76 ;;
        *) cat "$file"; dialog_msgbox "$title" '' 8 60 ;;
    esac
)
