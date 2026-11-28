module_options+=(
    ["module_spi1_panel,feature"]="module_spi1_panel"
    ["module_spi1_panel,desc"]="Orange Pi Zero 2W and 3W bus and header profile preview and undo"
    ["module_spi1_panel,example"]="select state preview apply undo"
    ["module_spi1_panel,group"]="Kernel"
    ["module_spi1_panel,status"]="Preview"
    ["module_spi1_panel,author"]="@shipmarty43"
    ["module_spi1_panel,maintainer"]="@shipmarty43"
)

function _panel_py() { python3 "${script_dir:-/usr/bin}/../share/armbian-config/bus_panel.py" --board "$panel_board" "$@"; }
function _panel_locks() { echo /run/lock; }

function _panel_plan() (
    local panel_work=$1 target=$2 snapshot=$3 source_boot
    source_boot=$(_ups_dfr_boot)
    _panel_py stage "$source_boot" "$snapshot" "$panel_work" "$target" || return 1
    _ups_dfr_boot() { echo "$panel_work/boot"; }
    if [[ $panel_board == a733 ]]; then
        _panel_py a733-trees "$panel_work" || return 1
    else
        local name
        for name in before after; do
            _zero2w_overlay_prepare panel-tree "$panel_work/$name" "$panel_work/$name.dtb" sx1262 '' || return 1
        done
        if [[ -f "$panel_work/base.env" ]]; then
            _zero2w_overlay_prepare panel-tree "$panel_work/base.env" "$panel_work/base.dtb" sx1262 '' || return 1
        fi
    fi
    if ! _zero2w_validate_change "$panel_journal" "$panel_work" > "$panel_work/validation-log" 2>&1; then
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
    if [[ $panel_board == a733 ]]; then
        jq -r 'def rows: (.buses | join(", ") | if .=="" then "Контроллеры SPI выключены" else . end),
            (.rows[] | "\(.bus) CS\(.cs) · вывод \(.pin) · \(.device) · режим \(.mode) · предел DT \(.ceiling_hz // "—") Гц \(.endpoint // "")");
            "Сейчас", (.live|rows), "При следующей загрузке", (.current|rows),
            (if .changed then "После применения", (.candidate|rows) else empty end)'
        return
    fi
    jq -r --arg view "${1:-state}" 'def rows: .profile, (.rows[] | " CS\(.cs)  \(.device)  pin \(.pin // "?")/\(.pad // "?")  \(.requested_hz) Гц (макс. \(.ceiling_hz)) \(.endpoint // "") \(.lock // "")"), ((.parked // {}) | to_entries[] | " CS\(.key) сохранено \(.value) Гц"); if $view=="candidate" then "После применения", (.candidate|rows)
        else "SPI1 · CLK 23 · MOSI 19 · MISO 21", "Сейчас", (.live|rows), "При следующей загрузке", (.current|rows) end'
}

function _panel_dialog() {
    local state group choice plan report undo output
    local -a choices=(pins 'Контакты сейчас и при следующей загрузке')
    state=$(module_spi1_panel state 2>&1) || { dialog_msgbox 'Шины и контакты' "$state" 14 78; return 1; }
    local g
    while IFS= read -r g; do choices+=("$g" "Маршруты · $g"); done < <(jq -r '.choices[].group' <<< "$state" | awk '!seen[$0]++')
    undo=$(jq -r '.undo // empty' <<< "$state")
    [[ -z $undo ]] || choices+=(undo 'Откатить последнее изменение')
    group=$(dialog_menu 'Шины и контакты' "Orange Pi $(jq -r .board <<< "$state") · 40-контактная гребёнка" 17 76 6 -- "${choices[@]}") || return 0
    if [[ $group == pins ]]; then
        mapfile -t choices < <(jq -r 'def owners: map(.label) | join(" + ") | if .=="" then "—" else . end;
            (.live.pins | INDEX(.pin | tostring)) as $live | .current.pins[] |
            (.pin|tostring), ("\(.pad)   " + (if $live[.pin|tostring] then ($live[.pin|tostring] | (.owners|owners) + (if .gpio_consumer then " [GPIO: " + .gpio_consumer + "]" else "" end)) else "нет данных" end)
                                    + " → " + (.owners|owners) + (if (.functions // [] | length)>0 then " · " + (.functions|join(" / ")) else "" end))' <<< "$state")
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
        if [[ $group == SPI1 || $group == SPI ]]; then report=$(_panel_summary <<< "$state") || return 1; fi
        choice=$(dialog_menu "$group" "$report" 23 90 9 -- "${choices[@]}") || return 0
        plan=$(module_spi1_panel preview "$choice" 2>&1) || { dialog_msgbox 'Предпросмотр' "$plan" 14 78; return 1; }
        local alternative
        alternative=$(jq -r '.alternative.id // empty' <<< "$plan")
        if [[ -n $alternative ]]; then
            report=$(jq -r '.issues[], "", .alternative.label' <<< "$plan")
            dialog_yesno 'Предпросмотр перехода?' "$report" 'Предпросмотр' 'Назад' 16 90 --defaultno || return 0
            choice=$alternative
            plan=$(module_spi1_panel preview "$choice" 2>&1) || { dialog_msgbox 'Предпросмотр' "$plan" 14 78; return 1; }
        fi
        report=$(jq -r 'def owners: map(.label) | join(" + ") | if .=="" then "—" else . end;
            .changes[] | "\(.pin) \(.pad)   \(.before|owners) → \(.after|owners)"' <<< "$plan") || return 1
        report="$(jq -r --arg id "$choice" '.transition // $id' <<< "$plan")"$'\n'"${report:-Назначения контактов совпадают.}"
        if [[ $group == SPI1 || $group == SPI ]]; then report+=$'\n'"$(_panel_summary candidate <<< "$plan")"; fi
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
    local panel_board panel_journal=spi1-panel
    panel_board=$(_header_gpio_board) || { echo "Expected Orange Pi Zero 2W or Zero 3W." >&2; return 1; }
    [[ $panel_board != a733 ]] || panel_journal=a733-panel
    case $op in
        select) _panel_dialog; return ;;
        state) [[ $# == 1 ]] || return 2; target=state ;;
        preview|apply)
            [[ ${2:-} =~ ^(a733-[a-z0-9-]{1,30}([+][a-z0-9-]{1,12}){0,19}|off|(shared|single|(i2c[0-4]|uart[2-5]|pwm[1-4])-[a-z][a-z0-9-]{0,12})([+][a-z0-9-]{1,12}){0,13})$ ]] || return 2
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
        _zero2w_overlay_change "$target" "$panel_journal" _panel_commit >&2 || return 1
        echo '{"saved":true}'
    else
        _panel_plan "$panel_workdir" "$target" "$root/armbianEnv.txt" && cat "$panel_workdir/result"
    fi
)
