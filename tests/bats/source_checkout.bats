#!/usr/bin/env bats
setup() {
    CHECKOUT="$BATS_TEST_TMPDIR/source tree"
    mkdir -p "$CHECKOUT/bin" "$CHECKOUT/tools" "$CHECKOUT/lib/armbian-config"
    cp "$BATS_TEST_DIRNAME/../../bin/armbian-config" "$CHECKOUT/bin/armbian-config"
}
@test "Unassembled source checkout reports build instruction before sudo or sourcing" {
    touch "$CHECKOUT/tools/config-assemble.sh"
    run bash "$CHECKOUT/bin/armbian-config" --api module_cpu_power status
    [ "$status" -eq 1 ]
    [[ "$output" == *'Source checkout is not built.'* && "$output" == *'config-assemble.sh" -p'* ]]
    [[ "$output" != *'command not found'* && "$output" != *'sudo:'* ]]
}
@test "Incomplete installed package reports the missing library" {
    run bash "$CHECKOUT/bin/armbian-config" --api module_cpu_power status
    [ "$status" -eq 1 ]
    [[ "$output" == *'Missing armbian-config library: config.initialize.sh'* ]]
}
@test "Missing assembled menu is rejected before modules execute" {
    for name in initialize functions docs system desktops network software runtime; do
        printf 'echo MODULE_MUST_NOT_RUN\n' > "$CHECKOUT/lib/armbian-config/config.$name.sh"
    done
    run bash "$CHECKOUT/bin/armbian-config" --api module_cpu_power status
    [ "$status" -eq 1 ]
    [[ "$output" == *'Missing armbian-config menu data'* && "$output" != *MODULE_MUST_NOT_RUN* ]]
}
