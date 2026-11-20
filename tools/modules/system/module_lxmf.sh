module_options+=(
    ["module_lxmf,feature"]="module_lxmf"
    ["module_lxmf,desc"]="Read LXMF messages and send to saved contacts"
    ["module_lxmf,example"]="select address"
    ["module_lxmf,group"]="Hardware"
    ["module_lxmf,status"]="Preview"
)

_lxmf_cli() {
    systemd-run --quiet --collect --wait --pipe -p DynamicUser=yes -p User=opi-reticulum \
        -p StateDirectory=opi-lxmf -p StateDirectoryMode=0700 -p PrivateDevices=yes \
        -p PrivateTmp=yes -p RuntimeMaxSec=20 /opt/opi-mesh/venv/bin/python /opt/opi-mesh/lxmf_mailbox.py "$@"
}

_lxmf_pick() {
    local title="$1" folder="$2" before=9223372036854775807 data key label choice
    local -a options
    while :; do
        data=$(_lxmf_cli list "$folder" "$before") || return 1
        if [[ -z "$data" ]]; then
            if [[ "$folder" == contacts ]]; then
                dialog_msgbox "$title" 'No saved contacts. Choose Add contact first.' 8 64 >&2
            else
                dialog_msgbox "$title" 'No messages in this folder.' 8 60 >&2
            fi
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

_lxmf_read() (
    local folder="$1" title="$2" selected file
    selected=$(_lxmf_pick "$title" "$folder") || return 0
    file=$(mktemp) || return 1
    trap 'rm -f -- "$file"' EXIT
    if ! _lxmf_cli show "$folder" "${selected%%$'\t'*}" > "$file"; then
        dialog_msgbox "$title" 'Could not read the selected message.' 8 60
        return 1
    fi
    case "$DIALOG" in
        dialog) dialog --title "$title" --textbox "$file" 20 76 ;;
        whiptail) whiptail --title "$title" --scrolltext --textbox "$file" 20 76 ;;
        *) cat "$file"; dialog_msgbox "$title" '' 8 60 ;;
    esac
)

_lxmf_save() {
    local id name title body result
    if [[ "$1" == add ]]; then
        name=$(dialog_inputbox 'Add LXMF contact' 'Contact name' '' 10 70) || return 0
        id=$(dialog_inputbox 'Add LXMF contact' 'LXMF delivery address (32 hex digits)' '' 10 70) || return 0
        result=$(printf '%s\0%s' "$name" "$id" | jq -Rsc 'split("\u0000") | {name:.[0],address:.[1]}' | _lxmf_cli add-contact 2>&1)
    else
        local selected
        selected=$(_lxmf_pick 'Send to contact' contacts) || return 0
        id=${selected%%$'\t'*}
        name=${selected#*$'\t'}
        title=$(dialog_inputbox 'Compose LXMF' "To $name — subject (optional)" '' 11 76) || return 0
        body=$(dialog_inputbox 'Compose LXMF' "To $name — message. Press OK to send." '' 12 76) || return 0
        result=$(printf '%s\0%s' "$title" "$body" | jq -Rsc 'split("\u0000") | {title:.[0],body:.[1]}' | _lxmf_cli send "$id" 2>&1)
    fi
    dialog_msgbox 'LXMF mailbox' "${result:-Mailbox command failed.}" 10 72
}

module_lxmf() {
    local choice result
    case "${1:-select}" in
        address) _lxmf_cli address; return ;;
        select) ;;
        *) return 2 ;;
    esac
    while :; do
        if ! systemctl is-active --quiet opi-lxmf.service; then
            choice=$(dialog_menu 'LXMF mailbox' 'Mailbox service is stopped.' 11 68 1 -- start 'Start mailbox') || return 0
            [[ "$choice" == start ]] || return 0
            systemctl start opi-lxmf.service || return 1
        fi
        choice=$(dialog_menu 'LXMF mailbox' 'Choose a mailbox action' 17 72 6 -- \
            inbox 'Read incoming messages' send 'Send to a saved contact' outbox 'Sent messages and delivery status' \
            add 'Add or rename a contact' address 'My LXMF delivery address') || return 0
        case "$choice" in
            inbox) _lxmf_read in 'LXMF inbox' ;;
            outbox) _lxmf_read out 'LXMF outbox' ;;
            add|send) _lxmf_save "$choice" ;;
            address) result=$(_lxmf_cli address 2>&1); dialog_msgbox 'My LXMF address' "$result" 9 62 ;;
            *) return 0 ;;
        esac
    done
}
