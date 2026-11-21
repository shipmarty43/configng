"""Configure the Zero 2W header PWM1 (PI11, physical pin 32)."""
import argparse
from decimal import Decimal
import os
from pathlib import Path
import re
import signal
import socket
import sys
from threading import Event

from h616_settings import load, save

PROFILE = Path("/etc/armbian-config/pwm1.json")
LEASE = Path("/run/opi-zero2w-pwm/lease.json")


def settings(hz, duty, polarity):
    if type(hz) is not int or not 1 <= hz <= 1_000_000:
        raise ValueError("PWM1 profile frequency must be 1..1000000 Hz")
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


def controller(sysroot=Path("/sys")):
    base = sysroot/"firmware/devicetree/base"
    channel = base/"soc/pwm1@0300a000"
    pins = base/"soc/pinctrl@300b000/pwm1-pi-pin"
    if b"xunlong,orangepi-zero2w" not in (base/"compatible").read_bytes().split(b"\0"):
        raise ValueError("Expected Orange Pi Zero 2W")
    handle = (pins/"phandle").read_bytes()
    if (len(handle) != 4 or not any(handle) or (channel/"pinctrl-0").read_bytes() != handle or
            (channel/"status").read_bytes() != b"okay\0" or
            (pins/"pins").read_bytes() != b"PI11\0" or (pins/"function").read_bytes() != b"pwm1\0"):
        raise ValueError("PWM1 is not routed to PI11; check the pwm1-pi11 overlay")
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


def remove_channel(chip):
    try:
        put(chip/"pwm1/enable", 0)
    finally:
        put(chip/"unexport", 1)


def identifier(chip):
    info = (chip/"pwm1").stat()
    return [chip.name, info.st_dev, info.st_ino]


def cleanup(chip, lease):
    if not lease.exists():
        return
    if (chip/"pwm1").exists() and identifier(chip) == load(lease):
        remove_channel(chip)
    lease.unlink()


def run(chip, profile, lease, ready, wait):
    period, high = waveform(profile)
    ch = chip/"pwm1"
    # Successful kernel export is the ownership boundary, including races with
    # WiringPi and other consumers. An EBUSY return must never trigger cleanup.
    put(chip/"export", 1)
    owned = None
    try:
        owned = identifier(chip)
        save(lease, owned)
        put(ch/"enable", 0)
        put(ch/"duty_cycle", 0)
        put(ch/"period", period)
        put(ch/"polarity", "normal")
        put(ch/"duty_cycle", high)
        put(ch/"enable", 1)
        for key, expected in (("period", period), ("duty_cycle", high),
                              ("polarity", "normal"), ("enable", 1)):
            if (ch/key).read_text().strip() != str(expected):
                raise ValueError("PWM driver request readback differs at " + key)
        ready()
        wait()
    finally:
        if owned is None or (ch.exists() and identifier(chip) == owned):
            remove_channel(chip)
        lease.unlink(missing_ok=True)


def notify():
    target = os.environ.get("NOTIFY_SOCKET")
    if target:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"READY=1", "\0" + target[1:] if target.startswith("@") else target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("status", "serve", "cleanup", "default", "validate"):
        sub.add_parser(action)
    cmd = sub.add_parser("set")
    cmd.add_argument("hz", type=int)
    cmd.add_argument("duty")
    cmd.add_argument("polarity", choices=("normal", "inversed"))
    args = parser.parse_args()
    if args.action == "default":
        PROFILE.unlink(missing_ok=True)
        print("Saved PWM1 profile cleared; an active output keeps its current waveform until stopped.")
        return
    if args.action == "set":
        profile = settings(args.hz, args.duty, args.polarity)
        save(PROFILE, profile)
        print(f"Saved for next start: {args.hz} Hz, {args.duty}% active, {args.polarity}")
        return
    if args.action == "validate":
        settings(**load(PROFILE))
        controller()
        return
    if args.action == "cleanup":
        if LEASE.exists():
            cleanup(controller(), LEASE)
        return
    if args.action == "status":
        print("PWM1 / PI11 / physical 32")
        if PROFILE.exists():
            p = settings(**load(PROFILE))
            print(f"Next start: {p['hz']} Hz, {p['duty']}% active, {p['polarity']}")
            period, high = waveform(p)
            print(f"Requested intervals: high {high} ns, low {period-high} ns")
        else:
            print("Next start: no saved waveform")
        try:
            chip = controller()
        except (FileNotFoundError, ValueError) as exc:
            print(f"Route unavailable: {exc}")
            return
        ch = chip/"pwm1"
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
    run(controller(), settings(**load(PROFILE)), LEASE, notify, stop.wait)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(str(exc))
