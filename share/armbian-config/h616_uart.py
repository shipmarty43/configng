"""Configure a free H616 DW APB UART through Linux termios."""
from array import array
import argparse
from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import termios

from console_tty import serial_users
from h616_settings import load, save
from uart_routes import ROUTES

SYS = Path("/sys")
BACKUPS = Path("/run/armbian-config/uart")
PROFILES = Path("/etc/armbian-config/uart")
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


class PortBusy(ValueError):
    pass


def configure(name, node, action, target=None):
    reason = busy(name)
    if reason:
        if action == "status":
            print(f"{name}: {reason}; UART{NODES[node.name]}")
            return
        raise PortBusy(f"{name}: {reason}")
    fd = os.open("/dev/" + name, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        flag = array("i", [0])
        fcntl.ioctl(fd, getattr(termios, "TIOCGEXCL", 0x80045440), flag, True)
        if flag[0]:
            raise PortBusy("UART is held exclusively")
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        if reason := busy(name, fd):
            raise PortBusy(f"UART became busy: {reason}")
        current = fields(termios.tcgetattr(fd))
        backup = BACKUPS / (name + ".json")
        if action == "status":
            print(f"UART{NODES[node.name]}: {describe(current)} (driver settings)")
            return
        if action == "rollback":
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


@contextmanager
def profile_lock(port):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    with (BACKUPS / (port + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def profile_record(port, baud, bits, parity, stops):
    framing(baud, bits, parity, stops)
    return {"port": port, "baud": baud, "bits": bits, "parity": parity, "stops": stops}


def read_profile(path, port):
    record = load(path)
    if not isinstance(record, dict) or set(record) != {"port", "baud", "bits", "parity", "stops"} or record["port"] != port:
        raise ValueError(f"Malformed saved profile for {port}")
    return profile_record(**record)


def header_pins(node, port):
    """Check the active controller's default mux before opening its tty."""
    group_root = node.parent / "pinctrl@300b000"
    handles = (node/"pinctrl-0").read_bytes()
    if not handles or len(handles) % 4:
        return False
    groups = {p.read_bytes(): p.parent for p in group_root.glob("*/phandle")}
    pins = []
    for i in range(0, len(handles), 4):
        group = groups.get(handles[i:i+4])
        if group is None or (group/"function").read_bytes() != port.encode() + b"\0":
            return False
        pins += (group/"pins").read_bytes().rstrip(b"\0").decode("ascii").split("\0")
    return pins == list(ROUTES[port][:2])


def reserved(name, gpsd=Path("/etc/default/gpsd"), gnss=Path("/etc/opi-gnss.json")):
    """Even a socket-activated receiver or login prompt may not have an fd yet."""
    if gnss.exists():
        cfg = load(gnss)
        if cfg.get("mode") in ("auto", "waveshare") and cfg.get("device") and Path(cfg["device"]).resolve() == Path("/dev")/name:
            return "configured Waveshare GNSS receiver"
    if gpsd.exists():
        for line in gpsd.read_text().splitlines():
            match = re.match(r"^\s*(?:export\s+)?DEVICES=(.*)$", line)
            if not match:
                continue
            for word in shlex.split(match[1], comments=True):
                for path in word.split():
                    if "$" in path or "`" in path:
                        return "dynamic gpsd device configuration"
                    if Path(path).resolve() == Path("/dev")/name:
                        return "configured gpsd receiver"
    result = subprocess.run(["systemctl", "is-enabled", "serial-getty@" + name + ".service"],
                            capture_output=True, text=True, timeout=8)
    if result.stdout.strip() in ("enabled", "enabled-runtime", "generated"):
        return "serial getty configured"
    return ""


def restore_profile(name):
    if not re.fullmatch(r"ttyS[0-9]+", name):
        raise ValueError("Expected a ttyS device")
    node = ports().get(name)
    if node is None:
        return
    port = f"uart{NODES[node.name]}"
    if port not in ROUTES:
        return
    path = PROFILES / (port + ".json")
    with profile_lock(port):
        if not path.exists():
            return
        record = read_profile(path, port)
        if not header_pins(node, port):
            raise ValueError(f"{port}: saved header route does not match live DT")
        reason = busy(name) or reserved(name)
        if reason:
            print(f"Skipped {port} on {name}: {reason}")
            return
        try:
            configure(name, node, "set", framing(record["baud"], record["bits"], record["parity"], record["stops"]))
        except PortBusy as exc:
            print(f"Skipped {port} on {name}: {exc}")
            return
        except OSError as exc:
            if exc.errno not in (errno.EBUSY, errno.EWOULDBLOCK):
                raise
            print(f"Skipped {port} on {name}: device busy")
            return
        print(f"Restored {port} on {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    sub.add_parser("rates")
    sub.add_parser("restore-profile").add_argument("tty")
    for action in ("save", "saved", "forget"):
        cmd = sub.add_parser(action)
        cmd.add_argument("port", choices=ROUTES)
        if action == "save":
            cmd.add_argument("baud", type=int)
            cmd.add_argument("bits", type=int)
            cmd.add_argument("parity")
            cmd.add_argument("stops")
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
    if args.action == "restore-profile":
        restore_profile(args.tty)
        return
    if args.action in ("save", "saved", "forget"):
        path = PROFILES / (args.port + ".json")
        with profile_lock(args.port):
            if args.action == "save":
                record = profile_record(args.port, args.baud, args.bits, args.parity, args.stops)
                save(path, record)
                print(f"Saved for {args.port} on header {ROUTES[args.port][2]} at device discovery")
            elif args.action == "forget":
                if path.exists():
                    path.unlink()
                    fd = os.open(PROFILES, os.O_DIRECTORY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                print(f"Cleared boot profile for {args.port}")
            elif path.exists():
                record = read_profile(path, args.port)
                print(describe(framing(record["baud"], record["bits"], record["parity"], record["stops"])))
            else:
                print("No saved boot profile")
        return
    devices = ports()
    if args.action == "list":
        for name, node in devices.items():
            print(f"{name}\tUART{NODES[node.name]}  {node.name}  {busy(name) or 'free'}")
        return
    node = devices.get(args.tty)
    if not node:
        raise ValueError("Expected an enabled H616 UART; see list")
    target = framing(args.baud, args.bits, args.parity, args.stops) if args.action == "set" else None
    configure(args.tty, node, args.action, target)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, termios.error) as error:
        sys.exit(str(error))
