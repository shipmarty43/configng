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

_lxmf_save() {
    local id name title body result
    if [[ "$1" == add ]]; then
        name=$(dialog_inputbox 'Add LXMF contact' 'Contact name' '' 10 70) || return 0
        id=$(dialog_inputbox 'Add LXMF contact' 'LXMF delivery address (32 hex digits)' '' 10 70) || return 0
        result=$(printf '%s\0%s' "$name" "$id" | jq -Rsc 'split("\u0000") | {name:.[0],address:.[1]}' | _lxmf_cli add-contact 2>&1)
    else
        local selected
        selected=$(_mesh_mail_pick 'Send to contact' contacts _lxmf_cli 'No saved contacts. Choose Add contact first.') || return 0
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
            inbox) _mesh_mail_read in 'LXMF inbox' _lxmf_cli ;;
            outbox) _mesh_mail_read out 'LXMF outbox' _lxmf_cli ;;
            add|send) _lxmf_save "$choice" ;;
            address) result=$(_lxmf_cli address 2>&1); dialog_msgbox 'My LXMF address' "$result" 9 62 ;;
            *) return 0 ;;
        esac
    done
}
