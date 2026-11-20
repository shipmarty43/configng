module_options+=(
    ["module_meshtastic_mail,feature"]="module_meshtastic_mail"
    ["module_meshtastic_mail,desc"]="Read simulator messages and send a direct text to a known node"
    ["module_meshtastic_mail,example"]="select"
    ["module_meshtastic_mail,group"]="Hardware"
    ["module_meshtastic_mail,status"]="Preview"
)

_meshtastic_mail_cli() {
    systemd-run --quiet --collect --wait --pipe -p DynamicUser=yes -p User=opi-meshtastic-mail \
        -p StateDirectory=opi-meshtastic-mail -p StateDirectoryMode=0700 -p PrivateDevices=yes \
        -p PrivateNetwork=yes -p RuntimeMaxSec=20 /opt/opi-mesh/venv/bin/python /opt/opi-mesh/meshtastic_mail.py "$@"
}

_meshtastic_compose() {
    local selected body result
    selected=$(_mesh_mail_pick 'Send to Meshtastic node' nodes _meshtastic_mail_cli \
        'No remote nodes discovered in this simulator.') || return 0
    body=$(dialog_inputbox 'Compose direct text' "To ${selected#*$'\t'} — message. Press OK to send." '' 12 76) || return 0
    result=$(printf '%s' "$body" | _meshtastic_mail_cli send "${selected%%$'\t'*}" 2>&1) || :
    dialog_msgbox 'Meshtastic messages' "${result:-Could not queue text.}" 9 72
}

module_meshtastic_mail() {
    local action
    if ! systemctl is-active --quiet opi-meshtastic-mail.service; then
        action=$(dialog_menu 'Meshtastic messages' 'Messaging service is stopped.' 11 68 1 -- start 'Start simulator messaging') || return 0
        [[ "$action" == start ]] || return 0
        systemctl start opi-meshtastic-mail.service || return 1
    fi
    while :; do
        action=$(dialog_menu 'Meshtastic messages' 'Choose a message action' 16 72 4 -- \
            inbox 'Read received texts' send 'Send direct text to a node' outbox 'Sent texts and acknowledgements' discover 'Discover simulator nodes') || return 0
        case "$action" in
            inbox) _mesh_mail_read in 'Meshtastic inbox' _meshtastic_mail_cli ;;
            send) _meshtastic_compose ;;
            discover)
                local result
                result=$(_meshtastic_mail_cli discover 2>&1)
                dialog_msgbox 'Discover nodes' "$result" 9 72 ;;
            outbox) _mesh_mail_read out 'Meshtastic outbox' _meshtastic_mail_cli ;;
            *) return 0 ;;
        esac
    done
}
