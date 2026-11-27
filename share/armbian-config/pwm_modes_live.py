"""One bounded operation on a booted header PWM profile."""
from contextlib import ExitStack
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from h616_pwm import chip_lock, put
from pwm_modes import FAN, MARK, channel, check, controller, decode
from uart_routes import cells, read_tree, strings


def timing(period, duty, dead=0):
    # Both BSPs use 24 MHz here. Stay on their unscaled path and avoid the
    # 256-tick boundary, which wraps in the eight-bit dead-zone field.
    cycles = period * 24 // 1000
    high = cycles * duty // period if period > 0 else 0
    ticks = dead * 24 // 1000
    if not 1000 <= period <= 2730666 or not 0 < duty < period:
        raise ValueError("Use period 1000..2730666 ns and duty strictly inside the period")
    if not (ticks < high and ticks < cycles - high) or (dead and not 1 <= ticks <= 255):
        raise ValueError("The high and low intervals must both exceed the hardware dead time")
    return ticks


def operate(profile, chip, args, *, write=put, read=lambda p: p.read_text().strip(),
            sleep=time.sleep, now=time.monotonic):
    mode = profile.mode
    n = profile.first % 10
    advanced = chip / "device" / "pulse_busy"
    parsed = chip / "device" / "header_pwm_profiles"
    if not parsed.is_file():
        raise ValueError("Boot the PWM002 driver patch for this board before a live test")
    bindings = {}
    for line in read(parsed).splitlines():
        idx, peer, dead_ns, count = map(int, line.split())
        bindings[idx] = (peer, dead_ns, count)
    for ch in profile.channels:
        expected = (ch ^ 1, profile.values[0], 0) if mode == "pair" else (
            255, 0, profile.values[0] if mode == "burst" else 0)
        if bindings.get(ch % 10) != expected:
            raise ValueError("The PWM driver did not load the saved channel parameters")
    if mode == "burst" and not advanced.is_file():
        raise ValueError("The driver cannot report burst completion")
    if mode == "pair":
        period, duty, duration = args
        ticks = timing(period, duty, profile.values[0])
        if not 1 <= duration <= 60000:
            raise ValueError("Pair test duration must be 1..60000 ms")
    elif mode == "burst":
        period, duty = args
        timing(period, duty)
    elif mode != "capture" or args:
        raise ValueError("Capture takes no waveform arguments")
    target = chip / f"pwm{n}"
    channels = [n] if mode == "capture" else [n, n ^ 1]
    with chip_lock(chip), ExitStack() as release:
        for idx in channels:
            write(chip / "export", idx)
            release.callback(write, chip / "unexport", idx)
            if read(chip / f"pwm{idx}/enable") != "0":
                raise ValueError("PWM already active")
        if mode == "capture":
            period, duty = map(int, read(target / "capture").split())
            if not 0 < duty < period:
                raise ValueError("No complete high/low pulse in the capture window")
            return f"Period {period} ns, high {duty} ns, {1e9/period:.2f} Hz, {100*duty/period:.2f}%"
        write(target / "duty_cycle", 0)
        write(target / "period", period)
        write(target / "duty_cycle", duty)
        write(target / "polarity", "normal")
        release.callback(write, target / "enable", 0)
        write(target / "enable", 1)
        if mode == "pair":
            sleep(duration / 1000)
            return f"Pair stopped. Configured dead time {ticks}/24 MHz ({ticks * 1000 / 24:.2f} ns)"
        deadline = now() + period * profile.values[0] / 1e9 + 1
        while int(read(advanced), 0) & (1 << n):
            if now() >= deadline:
                raise TimeoutError("Pulse counter did not finish")
            sleep(0.005)
        return f"Hardware burst complete ({profile.values[0]} programmed periods)"


def fan_drive(sysroot):
    base = (sysroot / "firmware/devicetree/base" / FAN.lstrip("/")).resolve()
    for dev in (sysroot / "class/hwmon").glob("hwmon*"):
        if (dev / "device/of_node").resolve() != base or not (dev / "pwm1").is_file():
            continue
        drive = int((dev / "pwm1").read_text())
        if not 0 <= drive <= 255:
            raise ValueError("Invalid fan drive reported by hwmon")
        report = f"Requested drive {drive}/255 ({100 * drive / 255:.1f}%)"
        if (dev / "fan1_input").is_file():
            report += f"\nMeasured RPM: {int((dev / 'fan1_input').read_text())}"
        return report
    return "Current fan drive unavailable from hwmon"


def main():
    board, op, *args = sys.argv[1:]
    sysroot = Path("/sys")
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "live.dtb"
        subprocess.run(["dtc", "-q", "-I", "fs", "-O", "dtb", "-o", dst,
                        sysroot / "firmware/devicetree/base"], check=True)
        nodes = read_tree(dst)
    if op == "fan":
        from pwm_modes import Profile
        if board != "a733" or FAN not in nodes:
            raise ValueError("No onboard PWM thermal fan in this board DT")
        levels = cells(nodes[FAN]["cooling-levels"])
        check(board, nodes, Profile(board, "fan", 5, (0, 50, 102, 170, 255)), applied=False)
        print("Live cooling levels (0..255):", " ".join(map(str, levels)))
        print(fan_drive(sysroot))
        return
    n, *params = map(int, args)
    names = strings(nodes.get(channel(board, n), {}).get(MARK, b""))
    if len(names) != 1:
        raise ValueError("No advanced PWM profile on this live channel; save a profile and reboot")
    name, = names
    profile = decode(name)
    if n != profile.first or profile.mode != op:
        raise ValueError("Boot the saved profile and use its first channel")
    check(board, nodes, profile, applied=True)
    ctrl = sysroot / "firmware/devicetree/base" / controller(board, n).lstrip("/")
    chips = [c for c in (sysroot / "class/pwm").glob("pwmchip*")
             if (c/"device/of_node").resolve() == ctrl.resolve() and
             (c/"device/driver").resolve().name == "sunxi_pwm" and
             (c/"npwm").read_text().strip() == ("6" if board == "h618" else "10")]
    if len(chips) != 1 or (op == "pair" and chips[0].name != "pwmchip0"):
        raise ValueError("Unexpected PWM device or pair base")
    print(operate(profile, chips[0], params))


if __name__ == "__main__":
    def stop(signum, frame):
        raise InterruptedError("PWM test interrupted")

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
