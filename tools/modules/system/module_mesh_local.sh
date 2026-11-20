module_options+=(
    ["module_mesh_local,feature"]="module_mesh_local"
    ["module_mesh_local,desc"]="Manage the Meshtastic simulator and Reticulum TCP service"
    ["module_mesh_local,example"]="select status meshtastic reticulum"
    ["module_mesh_local,group"]="Hardware"
    ["module_mesh_local,status"]="Preview"
    ["module_mesh_local,author"]="@shipmarty43"
)

function module_mesh_local() {
    local service action output result=0
    case "${1:-select}" in
        select)
            local -a mailbox=()
            if [[ -r /opt/opi-mesh/lxmf_mailbox.py ]]; then mailbox=(lxmf 'LXMF mailbox'); fi
            service=$(dialog_menu 'Mesh services' 'Choose a software node' 14 76 3 -- \
                meshtastic 'Meshtastic simulator (private network)' reticulum 'Reticulum over TCP' "${mailbox[@]}") || return 0
            if [[ "$service" == lxmf ]]; then module_lxmf select; return; fi
            local -a messaging=()
            if [[ "$service" == meshtastic && -f /opt/opi-mesh/meshtastic_mail.py ]]; then
                messaging=(messages 'Read and send Meshtastic texts')
            fi
            action=$(dialog_menu 'Mesh services' 'Choose an action' 17 76 5 -- \
                status 'Show service state' inspect 'Query the running node' start 'Start for this boot' stop 'Stop service' "${messaging[@]}") || return 0
            if [[ "$action" == messages ]]; then module_meshtastic_mail select; return; fi
            output=$(module_mesh_local "$service" "$action" 2>&1) || result=$?
            dialog_msgbox 'Mesh services' "${output:-Done.}" 20 76
            return "$result" ;;
        status) systemctl show -p Id -p ActiveState -p SubState opi-meshtastic-sim.service opi-reticulum.service; return ;;
        meshtastic) service=opi-meshtastic-sim.service ;;
        reticulum) service=opi-reticulum.service ;;
        *) echo 'Expected select, status, meshtastic or reticulum' >&2; return 2 ;;
    esac
    case "${2:-status}" in
        status) systemctl show -p Id -p ActiveState -p SubState -p UnitFileState "$service" ;;
        start|stop) systemctl "$2" "$service" ;;
        inspect)
            systemctl is-active --quiet "$service" || { echo 'Start the service first.' >&2; return 1; }
            if [[ "$1" == meshtastic ]]; then
                if [[ -f /opt/opi-mesh/meshtastic_mail.py ]] && systemctl is-active --quiet opi-meshtastic-mail.service; then
                    _meshtastic_mail_cli inspect
                    return
                fi
                systemd-run --quiet --collect --wait --pipe -p "JoinsNamespaceOf=$service" \
                    -p PrivateNetwork=yes -p PrivateDevices=yes -p DynamicUser=yes \
                    -p RuntimeMaxSec=25 /opt/opi-mesh/venv/bin/python /opt/opi-mesh/sim_info.py
            else
                systemd-run --quiet --collect --wait --pipe -p DynamicUser=yes -p User=opi-reticulum \
                    -p StateDirectory=opi-reticulum -p StateDirectoryMode=0700 -p PrivateDevices=yes \
                    -p RuntimeMaxSec=25 /opt/opi-mesh/venv/bin/rnstatus --config /var/lib/opi-reticulum
            fi ;;
        *) echo 'Expected status, inspect, start or stop' >&2; return 2 ;;
    esac
}
