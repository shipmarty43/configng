"""Guest assertions on real Linux power_supply, PWM sysfs and PTY."""
from pathlib import Path
import os
import pty
import termios

import h616_pwm as pwm
import h616_uart as uart

adapter, = (p for p in Path("/sys/bus/i2c/devices").glob("i2c-*")
            if (p/"name").read_text().startswith("Virtual TWI1 "))
hz = int((adapter/"name").read_text().split()[2])
assert hz in (100_000, 400_000)
battery, = Path("/sys/class/power_supply").glob("dfr0528-*")
assert (battery/"capacity").read_text().strip() == "51"
assert (battery/"voltage_now").read_text().strip() == "3593750"
assert (battery/"status").read_text().strip() == "Unknown"
print(f"PASS DFR0528 @{hz} Hz: real driver, 51%, 3593750 uV, status Unknown", flush=True)

chip = pwm.controller()
lease = Path("/run/test-pwm-lease")
for polarity, duty in (("normal", "25"), ("inversed", "37.5")):
    profile = pwm.settings(1000, duty, polarity)
    def active():
        assert (chip/"pwm1/enable").read_text().strip() == "1"
        assert (chip/"pwm1/polarity").read_text().strip() == polarity
        assert int((chip/"pwm1/duty_cycle").read_text()) == pwm.waveform(profile)[1]
        try:
            pwm.run(chip, profile, Path("/run/other-lease"), lambda: None, lambda: None)
        except OSError:
            pass
        else:
            raise AssertionError("foreign exported PWM was acquired")
        assert (chip/"pwm1/enable").read_text().strip() == "1"
    pwm.run(chip, profile, lease, active, lambda: None)
    assert not (chip/"pwm1").exists() and not lease.exists()
print("PASS PWM1 real kernel export/readback/release; 1000 Hz, 25% normal and 37.5% inversed", flush=True)
master, slave = pty.openpty()
try:
    old = uart.fields(termios.tcgetattr(slave))
    for rate in (9600, 115200, 921600):
        target = uart.framing(rate, 8, "none", "1")
        uart.apply(slave, target)
        assert uart.fields(termios.tcgetattr(slave)) == target
    uart.apply(slave, old)
    assert uart.fields(termios.tcgetattr(slave)) == old
finally:
    os.close(master)
    os.close(slave)
print("PASS ARM64 PTY baud/framing and restoration", flush=True)
