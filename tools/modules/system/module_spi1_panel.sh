module_options+=(
    ["module_spi1_panel,feature"]="module_spi1_panel"
    ["module_spi1_panel,desc"]="Zero 2W SPI1 bus and header profile preview and undo"
    ["module_spi1_panel,example"]="select state preview apply undo"
    ["module_spi1_panel,group"]="Kernel"
    ["module_spi1_panel,status"]="Preview"
    ["module_spi1_panel,author"]="@shipmarty43"
    ["module_spi1_panel,maintainer"]="@shipmarty43"
)

function _panel_py() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/bus_panel.py" "$@"; }
function _panel_locks() { echo /run/lock; }

function _panel_plan() (
    local panel_work=$1 target=$2 snapshot=$3 source_boot
    source_boot=$(_ups_dfr_boot)
    _panel_py stage "$source_boot" "$snapshot" "$panel_work" "$target" || return 1
    _ups_dfr_boot() { echo "$panel_work/boot"; }
    local name
    for name in before after; do
        _zero2w_overlay_prepare panel-tree "$panel_work/$name" "$panel_work/$name.dtb" sx1262 '' || return 1
    done
    if [[ -f "$panel_work/base.env" ]]; then
        _zero2w_overlay_prepare panel-tree "$panel_work/base.env" "$panel_work/base.dtb" sx1262 '' || return 1
    fi
    if ! _zero2w_validate_change spi1-panel "$panel_work" > "$panel_work/validation-log" 2>&1; then
        mv "$panel_work/validation-log" "$panel_work/validation-error" || return 1
    fi
    _panel_py describe "$panel_work" "$target" "$(_ups_dfr_dt)" "$(_sx1262_class)" "$(_panel_locks)" > "$panel_work/result"
)

# Invoked by the common boot writer inside its exclusive flock. A preview token
# binds the boot environment, both composed trees and the requested chip clocks.
function _panel_commit() {
    local key=token result
    [[ $1 != undo ]] || key=undo
    _panel_plan "$panel_workdir" "$1" "$2" || return 1
    if jq -e '.issues | length > 0' "$panel_workdir/result" >/dev/null; then
        jq -r '"CONFLICT: " + (.issues | join(" • "))' "$panel_workdir/result" >&2
        return 1
    fi
    result=$(jq -er --arg k "$key" '.[$k]' "$panel_workdir/result") || return 1
    if [[ $expected != "$result" ]]; then
        echo 'STALE: Конфигурация изменилась. Откройте новый предпросмотр.' >&2
        return 1
    fi
    _panel_py publish "$(_ups_dfr_boot)" "$panel_workdir" && cp "$panel_workdir/after" "$3"
}

function _panel_summary() {
    jq -r 'def rows: .profile, (.rows[] | " CS\(.cs)  \(.device)  pin \(.pin // "?")/\(.pad // "?")  \(.requested_hz) Гц (макс. \(.ceiling_hz)) \(.endpoint // "") \(.lock // "")"), ((.parked // {}) | to_entries[] | " CS\(.key) сохранено \(.value) Гц"); "SPI1 · CLK 23 · MOSI 19 · MISO 21", "Сейчас", (.live|rows), "При следующей загрузке", (.current|rows), (if .changed then "После применения", (.candidate|rows) else empty end)'
}

function _panel_dialog() {
    local state group choice plan report undo output
    local -a choices=(pins 'Контакты сейчас и при следующей загрузке' SPI1 'Радиопрофиль и частоты'
                      'I²C' 'Линии SCL/SDA' UART 'Последовательные порты' PWM 'Каналы PWM')
    state=$(module_spi1_panel state 2>&1) || { dialog_msgbox 'Шины и контакты' "$state" 14 78; return 1; }
    undo=$(jq -r '.undo // empty' <<< "$state")
    [[ -z $undo ]] || choices+=(undo 'Откатить последнее изменение')
    group=$(dialog_menu 'Шины и контакты' 'Orange Pi Zero 2W · 40-контактная гребёнка' 17 76 6 -- "${choices[@]}") || return 0
    if [[ $group == pins ]]; then
        mapfile -t choices < <(jq -r 'def owners: map(.label) | join(" + ") | if .=="" then "—" else . end;
            (.live.pins | INDEX(.pin | tostring)) as $live | .current.pins[] |
            (.pin|tostring), ("\(.pad)   " + (if $live[.pin|tostring] then ($live[.pin|tostring] | (.owners|owners) + (if .gpio_consumer then " [GPIO: " + .gpio_consumer + "]" else "" end)) else "нет данных" end)
                                    + " → " + (.owners|owners))' <<< "$state")
        report='Сейчас (DT, gpiochip недоступен) → следующая загрузка (DT)'
        if jq -e '.live.gpio_known' <<< "$state" >/dev/null; then report='Сейчас (DT и GPIO) → следующая загрузка (DT)'; fi
        dialog_menu 'Физические контакты' "$report" 23 90 14 -- "${choices[@]}" >/dev/null || :
        return 0
    elif [[ $group == undo ]]; then
        output=$(module_spi1_panel undo "$undo" 2>&1) || { dialog_msgbox 'Откат' "$output" 14 78; return 1; }
    else
        mapfile -t choices < <(jq -r --arg g "$group" '.choices[] | select(.group==$g) | .id, .label' <<< "$state")
        (( ${#choices[@]} )) || return 1
        report='Выберите маршрут для предпросмотра'
        if [[ $group == SPI1 ]]; then report=$(_panel_summary <<< "$state") || return 1; fi
        choice=$(dialog_menu "$group" "$report" 23 90 9 -- "${choices[@]}") || return 0
        plan=$(module_spi1_panel preview "$choice" 2>&1) || { dialog_msgbox 'Предпросмотр' "$plan" 14 78; return 1; }
        report=$(jq -r 'def owners: map(.label) | join(" + ") | if .=="" then "—" else . end;
            .changes[] | "\(.pin) \(.pad)   \(.before|owners) → \(.after|owners)"' <<< "$plan") || return 1
        report="$choice"$'\n'"${report:-Назначения контактов совпадают.}"
        if [[ $group == SPI1 ]]; then report+=$'\n'"$(_panel_summary <<< "$plan")"; fi
        if jq -e '.warnings | length > 0' <<< "$plan" >/dev/null; then report+=$'\n'"$(jq -r '.warnings[]' <<< "$plan")"; fi
        if jq -e '.issues | length > 0' <<< "$plan" >/dev/null; then
            dialog_msgbox 'Применение заблокировано' "$(jq -r '.issues[]' <<< "$plan")"$'\n'"$report" 22 90
            return 0
        fi
        if [[ $(jq -r .changed <<< "$plan") == false ]]; then
            dialog_msgbox 'Профиль уже выбран' "$report" 20 90; return 0
        fi
        dialog_yesno 'Сохранить для следующей загрузки?' "$report" 'Сохранить' 'Назад' 24 95 --defaultno || return 0
        output=$(module_spi1_panel apply "$choice" "$(jq -r .token <<< "$plan")" 2>&1) || { dialog_msgbox 'Шины и контакты' "$output" 14 78; return 1; }
    fi
    dialog_msgbox 'Шины и контакты' 'Сохранено для следующей загрузки.' 8 65
}

function module_spi1_panel() (
    local op=${1:-select} panel_workdir target expected='' root
    _ups_dfr_board || { echo 'Expected Orange Pi Zero 2W.' >&2; return 1; }
    case $op in
        select) _panel_dialog; return ;;
        state) [[ $# == 1 ]] || return 2; target=state ;;
        preview|apply)
            [[ ${2:-} =~ ^(shared|single|off|(i2c[0-4]|uart[2-5]|pwm[1-4])-[a-z][a-z0-9-]{0,12})$ ]] || return 2
            target=$2
            if [[ $op == apply ]]; then [[ $# == 3 ]] || return 2; expected=$3
            else [[ $# == 2 ]] || return 2; fi ;;
        undo) [[ $# == 2 ]] || return 2; expected=$2; target=undo ;;
        *) return 2 ;;
    esac
    panel_workdir=$(mktemp -d) || return 1
    trap 'rm -rf "$panel_workdir"' EXIT
    root=$(_ups_dfr_boot)
    if [[ $op == apply || $op == undo ]]; then
        [[ $expected =~ ^[0-9a-f]{64}$ ]] || return 2
        _zero2w_overlay_change "$target" spi1-panel _panel_commit >&2 || return 1
        echo '{"saved":true}'
    else
        _panel_plan "$panel_workdir" "$target" "$root/armbianEnv.txt" && cat "$panel_workdir/result"
    fi
)
