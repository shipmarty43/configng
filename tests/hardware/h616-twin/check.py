"""Guest assertions on real Linux power_supply, PWM sysfs and PTY."""
from pathlib import Path
import os
import pty
import termios
import subprocess
import sys
import time

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
        assert (chip/"pwm1/polarity").read_text().strip() == "normal"
        assert int((chip/"pwm1/duty_cycle").read_text()) == (250000 if polarity == "normal" else 625000)
        try:
            pwm.run(chip, profile, Path("/run/other-lease"), lambda: None, lambda: None)
        except OSError:
            pass
        else:
            raise AssertionError("foreign exported PWM was acquired")
        assert (chip/"pwm1/enable").read_text().strip() == "1"
    pwm.run(chip, profile, lease, active, lambda: None)
    assert not (chip/"pwm1").exists() and not lease.exists()
def wait_active(worker, ch):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            raise AssertionError(f"PWM worker exited with status {worker.returncode}")
        if (ch/"enable").exists() and (ch/"enable").read_text().strip() == "1":
            return
        time.sleep(.05)
    raise AssertionError(f"Timed out waiting for {ch}")


# Check the installed worker lifecycle as well as the synchronous lease.
helper = str(Path(pwm.__file__).resolve())
subprocess.run([sys.executable, helper, "set", "20000", "37.5", "inversed"], check=True)
for hard_stop in (False, True):
    worker = subprocess.Popen([sys.executable, helper, "serve"])
    try:
        wait_active(worker, chip/"pwm1")
        assert (chip/"pwm1/duty_cycle").read_text().strip() == "31250"
    finally:
        if hard_stop:
            worker.kill()
        else:
            worker.terminate()
        worker.wait(timeout=5)
    subprocess.run([sys.executable, helper, "cleanup"], check=True)
    assert not (chip/"pwm1").exists()
print("PASS PWM1 kernel readback: 1000 Hz 250000/625000 ns high; 20 kHz worker TERM/KILL cleanup", flush=True)
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

# Exercise every physical channel at once. The two boots may select different
# header routes; the saved waveform is always keyed by the channel number.
jobs = []
def command(n, *args):
    return [sys.executable, helper, "--channel", str(n), *args]
profiles = {1:(1000, "25", "normal"), 2:(2000, "37.5", "inversed"),
            3:(10000, "60", "normal"), 4:(20000, "50", "normal")}
try:
    for n, (freq, duty, polarity) in profiles.items():
        subprocess.run(command(n, "set", str(freq), duty, polarity), check=True)
        worker = subprocess.Popen(command(n, "serve"))
        jobs.append(worker)
        ch = chip/f"pwm{n}"
        wait_active(worker, ch)
    for n, (freq, duty, polarity) in profiles.items():
        path = chip/f"pwm{n}"
        period, high = pwm.waveform(pwm.settings(freq, duty, polarity))
        assert int((path/"period").read_text()) == period
        assert int((path/"duty_cycle").read_text()) == high
        print(f"PASS PWM{n} {pwm.live_pin(Path('/sys'), n)} {freq} Hz: {high}/{period} ns", flush=True)
    for n in (2, 4):
        try:
            pwm.check_pair(chip, n, 1_000_000_000)
        except ValueError as exc:
            assert f"PWM{n ^ 1}" in str(exc)
        else:
            raise AssertionError("shared divider conflict accepted")
    jobs[1].terminate()
    jobs[1].wait(timeout=5)
    assert not (chip/"pwm2").exists()
    assert all((chip/f"pwm{n}/enable").read_text().strip() == "1" for n in (1,3,4))
finally:
    for worker in jobs:
        worker.terminate()
    for worker in jobs:
        worker.wait(timeout=5)
assert all(not (chip/f"pwm{n}").exists() for n in range(6))
print("PASS four independent workers, shared-clock guards and channel-local stop", flush=True)
