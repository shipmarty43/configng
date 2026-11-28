# Sourced by the VM guest lifecycle test. Only the packaged entry points edit /boot.
kit_api() (
    # Same functions as --api, without reinitialising the terminal between batch reads.
    script_dir=/opt/armbian-config-zero2w/bin
    set +u
    declare -A module_options
    source "$script_dir/../lib/armbian-config/config.system.sh"
    set -u
    "$@"
)
kit_backup() { sed -n 's/.*Backup: .*\/\(change\.[[:alnum:]]*\).*/\1/p' | tail -1; }
kit_compare_env() {
    PYTHONPATH=/opt/armbian-config-zero2w/share/armbian-config python3 - "$1" <<'PYENV'
from pathlib import Path
import sys
from uart_routes import env_content
if env_content(Path(sys.argv[1]).read_text()) != env_content(Path("/boot/armbianEnv.txt").read_text()):
    raise SystemExit("Boot variable, duplicate key or comment changed")
PYENV
}
kit_save() {
    local first=0
    if [[ $BOARD == orangepizero2w ]]; then
        first=2
        kit_api module_h616_pwm pwm2 route PI12 | kit_backup > result/route2
        kit_api module_h616_pwm pwm3 route PI13 | kit_backup > result/route3
    fi
    python3 input/menu.py
    kit_api module_pwm_modes backups | tail -1 > result/pair-id
    grep -Eq "opi-pwmx-.*-pair-$first-500" /boot/armbianEnv.txt
    if [[ $BOARD == orangepizero3w ]]; then
        kit_api module_pwm_modes set fan 5 0 64 128 192 255 | kit_backup > result/fan-id
    fi
    kit_api module_pwm_modes verify
    cp /boot/armbianEnv.txt result/profile.env
    sha256sum /boot/overlay-user/opi-pwmx-*.dtbo > result/profile.sha
}
kit_check() {
    local module
    sha256sum -c result/profile.sha
    kit_compare_env result/profile.env
    kit_api module_pwm_modes verify
    kit_api module_pwm_modes list | grep -F pair
    for module in opi_header_gpio opi_i2c_recovery; do modprobe "$module"; test -d "/sys/module/$module"; done
    if [[ $BOARD == orangepizero2w ]]; then modprobe dfr0528_battery; test -d /sys/module/dfr0528_battery; fi
    if [[ $BOARD == orangepizero3w ]]; then kit_api module_pwm_modes list | grep '0-64-128-192-255'; fi
    if [[ -f input/qa_i2c.ko ]]; then
        # Use the packaged Python and the real recovery bridge. Only the adapter is a double.
        local diag=/opt/armbian-config-zero2w/share/armbian-config/header_bus_diag.py bus
        echo "Checking the virtual kernel adapter"; sync
        insmod input/qa_i2c.ko
        bus=$(python3 "$diag" i2c list); [[ $bus =~ ^i2c-[0-9]+$ ]]
        python3 "$diag" i2c status "$bus" | grep 'adapter recovery supported'
        if [[ $BOARD == orangepizero2w ]]; then
            local battery=/sys/class/power_supply/dfr0528-${bus#i2c-}-0010
            [[ $(cat "$battery/capacity") == 51 && $(cat "$battery/voltage_now") == 3593750 ]]
            [[ $(cat "$battery/status") == Unknown ]]
            echo "PASS native DFR0528 power_supply on updated kernel, 51%, 3593750 uV"
        fi
        python3 "$diag" i2c recover "$bus" | grep 'completed'
        for fault in 1 2 3; do
            echo "$fault" > /sys/module/qa_i2c/parameters/fault
            if python3 "$diag" i2c recover "$bus" >result/recovery-error 2>&1; then return 1; fi
            case $fault in 1|2) grep -F '[Errno 16]' result/recovery-error ;; 3) grep -F '[Errno 110]' result/recovery-error ;; esac
        done
        rmmod qa_i2c; insmod input/qa_i2c.ko supported=0
        bus=$(python3 "$diag" i2c list)
        python3 "$diag" i2c status "$bus" | grep 'recovery unsupported'
        if python3 "$diag" i2c recover "$bus"; then return 1; fi
        rmmod qa_i2c
        echo "PASS I2C recovery: release after clocks, stuck SDA/SCL, timeout, unsupported adapter"
    fi
    if [[ -f input/qa_gpio.ko ]]; then
        echo "Checking the two virtual GPIO chips"; sync
        insmod input/qa_gpio.ko
        python3 - <<'PYGPIO'
import errno
import wiringpi_zero3w as gpio
import wiringpi_zero2w as other
assert len(list(gpio.header_map())) == 28 and gpio.native_pin(16) == 354
with gpio.request_output(3, initial=1) as main, gpio.request_output(16, initial=0) as standby:
    assert (main.read(),standby.read()) == (1,0)
    standby.write(1); main.write(0)
    assert (main.read(),standby.read()) == (0,1)
    assert gpio.line_info(16).used
    try: gpio.request_input(16)
    except OSError as err: assert err.errno == errno.EBUSY
    else: raise AssertionError("duplicate GPIO claim")
assert not gpio.line_info(3).used and not gpio.line_info(16).used
try: other.request_input(16)
except OSError as err: assert err.errno == errno.ENODEV
else: raise AssertionError("wrong board binding")
PYGPIO
        rmmod qa_gpio
        echo "PASS WiringPi Python across PIO and R_PIO on native ARM64 kernel"
    else
        python3 -c 'import wiringpi_zero2w as g; assert g.native_pin(16)==270 and len(list(g.header_map()))==28'
    fi
    echo "PASS saved profile and packaged helpers after native reboot"
}
kit_undo() {
    if [[ $BOARD == orangepizero3w ]]; then kit_api module_pwm_modes rollback "$(cat result/fan-id)"; fi
    kit_api module_pwm_modes rollback "$(cat result/pair-id)"
    if [[ $BOARD == orangepizero2w ]]; then
        kit_api module_h616_pwm boot-rollback "$(cat result/route3)"
        kit_api module_h616_pwm boot-rollback "$(cat result/route2)"
    fi
}
