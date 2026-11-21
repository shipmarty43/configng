"""Configure the four hardware PWM channels on the Zero 2W header."""
import argparse
from contextlib import contextmanager
import fcntl
from decimal import Decimal
import os
from pathlib import Path
import re
import signal
import socket
import sys
from threading import Event

from h616_settings import load, save
from pwm_routes import CTRL, PINS, channel_node, group_name
from uart_routes import cells, strings

PROFILE = Path("/etc/armbian-config/pwm1.json")
LEASE = Path("/run/opi-zero2w-pwm/lease.json")


def settings(hz, duty, polarity):
    if type(hz) is not int or not 1 <= hz <= 1_000_000:
        raise ValueError("PWM profile frequency must be 1..1000000 Hz")
    if not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,2})?", str(duty)) or Decimal(str(duty)) > 100:
        raise ValueError("Duty must be 0..100 percent, with at most two decimal places")
    if polarity not in ("normal", "inversed"):
        raise ValueError("Polarity must be normal or inversed")
    return {"hz": hz, "duty": str(duty), "polarity": polarity}


def waveform(profile):
    period = (1_000_000_000 + profile["hz"] // 2) // profile["hz"]
    basis_points = int(Decimal(profile["duty"]) * 100)
    active = (period * basis_points + 5000) // 10000
    # sunxi_pwm_enable() forces normal polarity. Program the high interval
    # explicitly so the requested steady-state low/high widths hold on stock.
    return period, active if profile["polarity"] == "normal" else period - active


def live_pin(sysroot, n):
    base = sysroot/"firmware/devicetree/base"
    if b"xunlong,orangepi-zero2w" not in (base/"compatible").read_bytes().split(b"\0"):
        raise ValueError("Expected Orange Pi Zero 2W")
    channel = base/channel_node(n).lstrip("/")
    ctrl = base/CTRL.lstrip("/")
    if not (channel/"pinctrl-0").is_file():
        raise ValueError(f"PWM{n} has no live header route")
    if "allwinner,sun50i-h616-pwm" not in strings((ctrl/"compatible").read_bytes()):
        raise ValueError("Unexpected PWM controller")
    phandle = (channel/"phandle").read_bytes()
    refs = cells((ctrl/"sunxi-pwms").read_bytes())
    if (len(refs) != 6 or len(phandle) != 4 or refs[n] != int.from_bytes(phandle, "big")
            or (ctrl/"status").read_bytes().rstrip(b"\0") not in (b"ok", b"okay")
            or (channel/"status").read_bytes().rstrip(b"\0") not in (b"ok", b"okay")
            or (channel/"compatible").read_bytes() != f"allwinner,sunxi-pwm{n}\0".encode()
            or (channel/"pinctrl-names").read_bytes() != b"default\0"):
        raise ValueError(f"Unqualified PWM{n} controller route")
    for prop, expected in (("bind_pwm", 255), ("clk_bypass_output", 0)):
        if (channel/prop).exists() and cells((channel/prop).read_bytes()) != [expected]:
            raise ValueError(f"PWM{n} uses a paired or clock bypass configuration")
    ref = (channel/"pinctrl-0").read_bytes()
    for pin in PINS[n]:
        group = base/"soc/pinctrl@300b000"/group_name(n, pin)
        if (len(ref) == 4 and any(ref) and (group/"phandle").is_file()
                and (group/"phandle").read_bytes() == ref and strings((group/"pins").read_bytes()) == [pin]
                and strings((group/"function").read_bytes()) == [f"pwm{n}"]):
            check_uart_pin(base, pin)
            return pin
    raise ValueError(f"PWM{n} is not routed to a supported header pin")


def check_uart_pin(base, pin):
    pio = base/"soc/pinctrl@300b000"
    groups = {f.parent.joinpath("phandle").read_bytes() for f in pio.glob("*/pins")
              if pin in strings(f.read_bytes()) and (f.parent/"phandle").exists()}
    for serial in (base/"soc").glob("serial@*"):
        if (serial/"status").exists() and strings((serial/"status").read_bytes()) not in (["okay"], ["ok"]):
            continue
        for state in serial.glob("pinctrl-[0-9]*"):
            if any(ref.to_bytes(4, "big") in groups for ref in cells(state.read_bytes())):
                raise ValueError(f"{pin} is also claimed by live {serial.name}")


def controller(sysroot=Path("/sys"), n=1):
    live_pin(sysroot, n)
    base = sysroot/"firmware/devicetree/base"
    found = []
    for chip in (sysroot/"class/pwm").glob("pwmchip*"):
        device = (chip/"device").resolve()
        if (device.name == "300a000.pwm" and (device/"driver").resolve().name == "sunxi_pwm" and
                (device/"of_node").resolve() == (base/"soc/pwm@300a000").resolve() and
                (chip/"npwm").read_text().strip() == "6"):
            found.append(chip)
    if len(found) != 1:
        raise ValueError("Expected one H616 sysfs PWM controller")
    return found[0]


def put(path, value):
    path.write_text(str(value))


def pair_clock(period):
    """PCCR source/divider chosen by sunxi_pwm_config_single on 6.18.57."""
    if period <= 10:
        return None  # The bypass path leaves DIV_M unchanged.
    source = 100_000_000 if period <= 334 else 24_000_000
    cycles = source * period // 1_000_000_000
    for shift in range(9):
        if (cycles >> shift) // 257 <= 65536:
            return source, shift
    return None


def check_pair(chip, n, period):
    peer = n ^ 1
    required = pair_clock(period)
    def compatible(other):
        if required != pair_clock(other):
            raise ValueError(f"PWM{n} shares its clock with PWM{peer}: incompatible periods {period} and {other} ns")

    export = chip/f"pwm{peer}"
    if (export/"enable").exists() and (export/"enable").read_text().strip() == "1":
        compatible(int((export/"period").read_text()))
    ctrl = (chip/"device/of_node").resolve(strict=True)
    base = ctrl.parent.parent
    handle, = cells((ctrl/"phandle").read_bytes())
    controllers = {cells(p.with_name("phandle").read_bytes())[0]: cells(p.read_bytes())[0]
                   for p in base.rglob("#pwm-cells") if p.with_name("phandle").exists()}
    for prop in base.rglob("pwms"):
        if any((parent/"status").is_file() and (parent/"status").read_bytes().rstrip(b"\0") not in (b"ok", b"okay")
               for parent in (prop.parent, *prop.parent.parents) if parent.is_relative_to(base)):
            continue
        values = cells(prop.read_bytes())
        while values:
            provider, *args = values
            if provider == 0:  # Empty phandle entry
                values = args
                continue
            count = controllers.get(provider)
            if count is None or len(args) < count:
                raise ValueError(f"Malformed PWM consumer {prop.parent.name}")
            if provider == handle and count >= 2 and args[0] == peer:
                if "pwm-clock" not in strings((prop.parent/"compatible").read_bytes()):
                    raise ValueError(f"PWM{peer} clock is owned by {prop.parent.name}")
                compatible(args[1])
            values = args[count:]


@contextmanager
def chip_lock(chip):
    fd = os.open(chip, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def remove_channel(chip, n):
    try:
        put(chip/f"pwm{n}/enable", 0)
    finally:
        put(chip/"unexport", n)


def identifier(chip, n=1):
    info = (chip/f"pwm{n}").stat()
    return [chip.name, info.st_dev, info.st_ino]


def cleanup(chip, lease, n=1):
    with chip_lock(chip):
        if not lease.exists():
            return
        if (chip/f"pwm{n}").exists() and identifier(chip, n) == load(lease):
            remove_channel(chip, n)
        lease.unlink()


def run(chip, profile, lease, ready, wait, n=1):
    period, high = waveform(profile)
    ch = chip/f"pwm{n}"
    # Serialize pair checks and programming across our workers. Successful
    # export is the per-channel ownership boundary, including external users.
    exported = False
    owned = None
    try:
        with chip_lock(chip):
            put(chip/"export", n)
            exported = True
            owned = identifier(chip, n)
            save(lease, owned)
            check_pair(chip, n, period)
            put(ch/"enable", 0)
            put(ch/"duty_cycle", 0)
            put(ch/"period", period)
            put(ch/"polarity", "normal")
            put(ch/"duty_cycle", high)
            put(ch/"enable", 1)
            for key, expected in (("period", period), ("duty_cycle", high), ("polarity", "normal"), ("enable", 1)):
                if (ch/key).read_text().strip() != str(expected):
                    raise ValueError("PWM driver request readback differs at " + key)
        ready()
        wait()
    finally:
        if exported:
            with chip_lock(chip):
                if owned is None or (ch.exists() and identifier(chip, n) == owned):
                    remove_channel(chip, n)
                lease.unlink(missing_ok=True)


def notify():
    target = os.environ.get("NOTIFY_SOCKET")
    if target:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"READY=1", "\0" + target[1:] if target.startswith("@") else target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=PINS, type=int, default=1)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("status", "serve", "cleanup", "default", "validate"):
        sub.add_parser(action)
    cmd = sub.add_parser("set")
    cmd.add_argument("hz", type=int)
    cmd.add_argument("duty")
    cmd.add_argument("polarity", choices=("normal", "inversed"))
    args = parser.parse_args()
    n = args.channel
    path = PROFILE.with_name(f"pwm{n}.json")
    runtime = LEASE.parent if n == 1 else LEASE.parent.with_name(f"opi-zero2w-pwm-{n}")
    lease = Path(os.environ.get("RUNTIME_DIRECTORY", runtime)) / "lease.json"
    if args.action == "default":
        path.unlink(missing_ok=True)
        print(f"Saved PWM{n} profile cleared; an active output keeps its current waveform until stopped.")
        return
    if args.action == "set":
        profile = settings(args.hz, args.duty, args.polarity)
        save(path, profile)
        print(f"Saved for next start: {args.hz} Hz, {args.duty}% active, {args.polarity}")
        return
    if args.action == "validate":
        check_pair(controller(n=n), n, waveform(settings(**load(path)))[0])
        return
    if args.action == "cleanup":
        if lease.exists():
            cleanup(controller(n=n), lease, n)
        return
    if args.action == "status":
        print(f"PWM{n} header outputs: " + ", ".join(f"{pin} (pin {nr})" for pin, nr in PINS[n].items()))
        if path.exists():
            p = settings(**load(path))
            print(f"Next start: {p['hz']} Hz, {p['duty']}% active, {p['polarity']}")
            period, high = waveform(p)
            print(f"Requested intervals: high {high} ns, low {period-high} ns")
        else:
            print("Next start: no saved waveform")
        try:
            chip = controller(n=n)
            pin = live_pin(Path("/sys"), n)
            print(f"Live route: {pin}, physical {PINS[n][pin]}")
        except (FileNotFoundError, ValueError) as exc:
            print(f"Route unavailable: {exc}")
            return
        ch = chip/f"pwm{n}"
        print("Controller:", chip.name)
        if ch.exists():
            for key in ("enable", "period", "duty_cycle", "polarity"):
                print(f"{key}: {(ch/key).read_text().strip()}")
        else:
            print("Channel is not exported via sysfs")
        return
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(controller(n=n), settings(**load(path)), lease, notify, stop.wait, n)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(str(exc))
