"""Configure a free H616 DW APB UART through Linux termios."""
from array import array
import argparse
import fcntl
import os
from pathlib import Path
import re
import sys
import termios

from console_tty import serial_users
from h616_settings import load, save

SYS = Path("/sys")
BACKUPS = Path("/run/armbian-config/uart")
SPEEDS = {int(k[1:]): getattr(termios, k) for k in dir(termios)
          if re.fullmatch(r"B[0-9]+", k) and 0 < int(k[1:]) <= 4_000_000}
BITS = {n: getattr(termios, f"CS{n}") for n in range(5, 9)}
CMSPAR = getattr(termios, "CMSPAR", 0x40000000)
MASK = termios.CSIZE | termios.PARENB | termios.PARODD | termios.CSTOPB | CMSPAR
NODES = {f"serial@{0x5000000 + i*0x400:x}": i for i in range(6)}


def ports(sysroot=SYS, dev=Path("/dev")):
    base = sysroot/"firmware/devicetree/base"
    if not (base/"compatible").exists() or b"xunlong,orangepi-zero2w" not in (base/"compatible").read_bytes().split(b"\0"):
        return {}
    found = {}
    for tty in (sysroot/"class/tty").glob("ttyS*"):
        if not re.fullmatch(r"ttyS[0-9]+", tty.name) or not (dev/tty.name).is_char_device():
            continue
        device = (tty/"device").resolve()
        # serial-base can place a port device between the tty and DT platform device.
        node = None
        for parent in (device, *device.parents):
            if not parent.is_relative_to((sysroot/"devices").resolve()):
                break
            candidate = (parent/"of_node").resolve()
            if (parent/"driver").is_dir() and candidate.parent == (base/"soc").resolve() and candidate.name in NODES:
                node = candidate
                break
        if node is None:
            continue
        if b"snps,dw-apb-uart" not in (node/"compatible").read_bytes().split(b"\0"):
            continue
        if (node/"status").exists() and (node/"status").read_bytes().rstrip(b"\0") not in (b"okay", b"ok"):
            continue
        found[tty.name] = node
    return found


def busy(name, ignore_fd=None):
    consoles = {line.split()[0] for line in Path("/proc/consoles").read_text().splitlines() if line.split()}
    if name in consoles:
        return "kernel console"
    pids = sorted(serial_users(name, ignore_fd))
    return "open by PID " + ", ".join(pids) if pids else ""


def fields(attrs):
    return [attrs[2] & MASK, attrs[4], attrs[5]]


def framing(baud, bits, parity, stops):
    if baud not in SPEEDS or bits not in BITS or parity not in ("none", "even", "odd"):
        raise ValueError("Unsupported baud rate, character width or parity")
    long_stop = "1.5" if bits == 5 else "2"
    if stops not in ("1", long_stop):
        raise ValueError(f"For {bits} data bits select 1 or {long_stop} stop bits")
    flags = BITS[bits]
    if parity != "none":
        flags |= termios.PARENB
        if parity == "odd":
            flags |= termios.PARODD
    if stops != "1":
        flags |= termios.CSTOPB
    return [flags, SPEEDS[baud], SPEEDS[baud]]


def apply(fd, target):
    before = termios.tcgetattr(fd)
    new = before.copy()
    new[2] = (new[2] & ~MASK) | target[0]
    new[4:6] = target[1:]
    try:
        termios.tcsetattr(fd, termios.TCSANOW, new)
        if fields(termios.tcgetattr(fd)) != target:
            raise ValueError("UART driver did not accept the requested framing")
    except (termios.error, OSError, ValueError):
        termios.tcsetattr(fd, termios.TCSANOW, before)
        raise
    return fields(before)


def describe(state):
    flags, _, speed = state
    baud = next((hz for hz, code in SPEEDS.items() if code == speed), "custom")
    bits = next(n for n, code in BITS.items() if flags & termios.CSIZE == code)
    parity = ("mark" if flags & termios.PARODD else "space") if flags & CMSPAR else ("odd" if flags & termios.PARODD else "even")
    stops = ("1.5" if bits == 5 else "2") if flags & termios.CSTOPB else "1"
    return f"{baud} baud, {bits} bits, {parity if flags & termios.PARENB else 'none'} parity, {stops} stop"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    sub.add_parser("rates")
    for action in ("status", "set", "rollback"):
        cmd = sub.add_parser(action)
        cmd.add_argument("tty")
        if action == "set":
            cmd.add_argument("baud", type=int)
            cmd.add_argument("bits", type=int)
            cmd.add_argument("parity")
            cmd.add_argument("stops")
    args = parser.parse_args()
    if args.action == "rates":
        print("\n".join(map(str, sorted(SPEEDS))))
        return
    devices = ports()
    if args.action == "list":
        for name, node in devices.items():
            print(f"{name}\tUART{NODES[node.name]}  {node.name}  {busy(name) or 'free'}")
        return
    node = devices.get(args.tty)
    if not node:
        raise ValueError("Expected an enabled H616 UART; see list")
    reason = busy(args.tty)
    if reason:
        if args.action == "status":
            print(f"{args.tty}: {reason}; UART{NODES[node.name]}")
            return
        raise ValueError(f"{args.tty}: {reason}")
    target = framing(args.baud, args.bits, args.parity, args.stops) if args.action == "set" else None
    fd = os.open("/dev/" + args.tty, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        flag = array("i", [0])
        fcntl.ioctl(fd, getattr(termios, "TIOCGEXCL", 0x80045440), flag, True)
        if flag[0]:
            raise ValueError("UART is held exclusively")
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        if reason := busy(args.tty, fd):
            raise ValueError(f"UART became busy: {reason}")
        current = fields(termios.tcgetattr(fd))
        backup = BACKUPS / (args.tty + ".json")
        if args.action == "status":
            print(f"UART{NODES[node.name]}: {describe(current)} (driver settings)")
            return
        if args.action == "rollback":
            saved = load(backup)
            if saved["node"] != node.name or saved["after"] != current:
                raise ValueError("UART route or settings changed since the saved change")
            apply(fd, saved["before"])
            backup.unlink()
        elif current != target:
            before = apply(fd, target)
            try:
                save(backup, {"node": node.name, "before": before, "after": target})
            except OSError:
                apply(fd, before)
                raise
        print(describe(fields(termios.tcgetattr(fd))))
    finally:
        try:
            if exclusive:
                fcntl.ioctl(fd, termios.TIOCNXCL)
        finally:
            os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, termios.error) as error:
        sys.exit(str(error))
