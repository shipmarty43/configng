"""Persistent termios profiles for the three vendor Zero 3W header UARTs."""
import argparse
import errno
from pathlib import Path
import re
import sys
import termios

from a733_io import DE_PROP, FLOW_PROP, PIO, R_PIO, ROUTES, SOC, UART_FLOW
import h616_uart as serial
from h616_settings import save

PROFILES = Path("/etc/armbian-config/a733-uart")
PORTS = {name:route for name, route in ROUTES.items() if name.startswith("uart")}


def identify(name, sysroot=Path("/sys")):
    if not re.fullmatch(r"ttyS[0-9]+", name):
        raise ValueError("Expected a serial tty")
    base = sysroot / "firmware/devicetree/base"
    if not (base/"compatible").is_file() or not {b"xunlong,orangepi-zero3w", b"arm,sun60iw2p1"} <= set((base/"compatible").read_bytes().split(b"\0")):
        return None
    dev = (sysroot/"class/tty"/name/"device").resolve()
    for parent in (dev, *dev.parents):
        if not parent.is_relative_to((sysroot/"devices").resolve()):
            break
        node = (parent/"of_node").resolve()
        for port, (addr, function, pins, _) in PORTS.items():
            if node != (base/(SOC+addr).lstrip("/")).resolve() or not (parent/"driver").is_dir():
                continue
            group_root = base/(R_PIO if port == "uart7" else PIO).lstrip("/")
            if ((node/"compatible").read_bytes().split(b"\0")[0] != b"allwinner,uart-v100" or
                    (node/"status").is_file() and (node/"status").read_bytes().rstrip(b"\0") not in (b"ok", b"okay")):
                return None
            if (node/FLOW_PROP).exists() or (node/DE_PROP).exists():
                marker = DE_PROP if (node/DE_PROP).exists() else FLOW_PROP
                if ((node/FLOW_PROP).exists() and (node/DE_PROP).exists() or port not in UART_FLOW or (node/marker).read_bytes() != b"a733\0"
                        or not (node/"uart-has-rtscts").is_file()
                        or any((node/key).exists() for key in serial.FLOW_CONFLICTS)
                        or (node/(port+"_type")).read_bytes() != (4).to_bytes(4, "big")):
                    return None
                pins += " " + UART_FLOW[port][0]
            handle = (node/"pinctrl-0").read_bytes()
            if len(handle) != 4:
                return None
            for phandle in group_root.glob("*/phandle"):
                if phandle.read_bytes() == handle:
                    group = phandle.parent
                    if ((group/"function").read_bytes().rstrip(b"\0").decode() == function and
                            (group/"pins").read_bytes().rstrip(b"\0").decode().split("\0") == pins.split()):
                        return port, node
    return None


def restore(name):
    match = identify(name)
    if match is None:
        return
    port, node = match
    path = PROFILES / (port + ".json")
    flow = (node / FLOW_PROP).exists()
    if not flow and not path.exists():
        return
    with serial.profile_lock("a733-" + port):
        target = None
        if path.exists():
            record = serial.read_profile(path, port)
            target = serial.framing(record["baud"], record["bits"], record["parity"], record["stops"])
        elif not flow:
            return
        reason = serial.busy(name) or serial.reserved(name)
        if reason:
            print(f"Skipped {port}: {reason}")
            return
        try:
            if flow:
                serial.configure(name, node, "set", target, label=port.upper(), flow=True)
            else:
                serial.configure(name, node, "set", target, label=port.upper())
        except serial.PortBusy as err:
            print(f"Skipped {port}: {err}")
        except OSError as err:
            if err.errno not in (errno.EBUSY, errno.EWOULDBLOCK):
                raise
            print(f"Skipped {port}: tty busy")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    sub.add_parser("restore").add_argument("tty")
    for action in ("save","show","forget"):
        cmd = sub.add_parser(action)
        cmd.add_argument("port", choices=PORTS)
        if action == "save":
            cmd.add_argument("baud", type=int)
            cmd.add_argument("bits", type=int)
            cmd.add_argument("parity")
            cmd.add_argument("stops")
    args = cli.parse_args()
    if args.action == "restore":
        return restore(args.tty)
    path = PROFILES/(args.port+".json")
    with serial.profile_lock("a733-" + args.port):
        if args.action == "save":
            save(path, serial.profile_record(args.port,args.baud,args.bits,args.parity,args.stops))
        elif args.action == "forget":
            path.unlink(missing_ok=True)
        if path.exists():
            record = serial.read_profile(path, args.port)
            print(serial.describe(serial.framing(record["baud"],record["bits"],record["parity"],record["stops"])))
        else:
            print("No saved UART profile")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, termios.error) as error:
        sys.exit(str(error))
