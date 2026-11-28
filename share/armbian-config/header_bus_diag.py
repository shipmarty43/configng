"""Live diagnostics for the Zero 2W and Zero 3W header buses."""
import argparse
from array import array
import errno
import fcntl
import os
from pathlib import Path
import re
import sys
import termios

from a733_io import ROUTES as A_ROUTES, SOC
import a733_uart
from header_gpio import BOARD
from i2c_clocks import BUSES
import h616_uart as uart
from uart_routes import DE_PROP, strings

STATUS, RECOVER = 0xC00C4F61, 0x400C4F62
GET_RS485, SET_RS485 = 0x542E, 0x542F
RS_ENABLED, RTS_ON_SEND, RTS_AFTER_SEND = 1, 2, 4


def board_name(base):
    compat = strings((base / "compatible").read_bytes())
    for board, required in BOARD.items():
        if set(required) <= set(compat):
            return board
    raise ValueError("Expected an Orange Pi Zero 2W or Zero 3W")


def adapters(sysroot):
    base = sysroot / "firmware/devicetree/base"
    board = board_name(base)
    paths = ({int(k[-1]): v for k,v in BUSES.items() if k.startswith("twi")} if board == "h618" else
             {int(k[-1]): SOC+v[0] for k,v in A_ROUTES.items() if k.startswith("i2c")})
    result = {}
    for dev in (sysroot/"bus/i2c/devices").glob("i2c-*"):
        if not re.fullmatch(r"i2c-[0-9]+", dev.name):
            continue
        for idx, path in paths.items():
            if (dev/"of_node").resolve() == base/path.lstrip("/"):
                result[dev.name] = idx
    return result


def recovery(name, do_recover=False, sysroot=Path("/sys"), helper=Path("/dev/opi-i2c-recovery")):
    ids = adapters(sysroot)
    if name not in ids:
        raise ValueError("Adapter does not match a live board controller")
    bus = array("I", [int(name[4:]), ids[name], 0])
    dev = sysroot/"bus/i2c/devices"
    clients = sorted(c.name.split("-",1)[1] + " " + (c/"name").read_text().strip()
                     for c in dev.glob(f"{bus[0]}-????") if (c/"name").is_file())
    description = f"{name}, TWI{bus[1]}; registered clients: " + (", ".join(clients) or "none")
    if not helper.exists():
        if do_recover:
            raise ValueError("Install and load opi_i2c_recovery for this kernel")
        return description + "; recovery capability unknown (helper unavailable)"
    with helper.open("rb+", buffering=0) as fd:
        fcntl.ioctl(fd, STATUS, bus, True)
        if do_recover:
            if not bus[2]:
                raise OSError(errno.EOPNOTSUPP, "Adapter driver has no recovery callback")
            fcntl.ioctl(fd, RECOVER, bus, True)
            return description + "; kernel recovery completed"
    return description + ("; adapter recovery supported" if bus[2] else "; recovery unsupported")


def rs485(fd, mode, *, has_de=False):
    before = array("I", [0]*8)
    fcntl.ioctl(fd, GET_RS485, before, True)
    if mode == "status":
        return f"flags={before[0]:#x}, delay before/after TX={before[1]}/{before[2]} ms"
    if mode not in ("off","high","low"):
        raise ValueError("Choose off, high or low")
    if mode != "off":
        if not has_de:
            raise ValueError("The active pinmux does not route header RTS/DE")
        if termios.tcgetattr(fd)[2] & termios.CRTSCTS:
            raise ValueError("RTS is used by UART hardware flow control")
    target = array("I", before)
    if mode == "off":
        target[0] &= ~RS_ENABLED
    else:
        target[0] = (target[0] & ~(RTS_ON_SEND | RTS_AFTER_SEND)) | RS_ENABLED | (RTS_ON_SEND if mode == "high" else RTS_AFTER_SEND)
    fcntl.ioctl(fd, SET_RS485, target, True)
    try:
        actual = array("I", [0]*8)
        fcntl.ioctl(fd, GET_RS485, actual, True)
        mask = RS_ENABLED if mode == "off" else RS_ENABLED | RTS_ON_SEND | RTS_AFTER_SEND
        if (actual[0] & mask) != (target[0] & mask) or (mode != "off" and actual[1:3] != before[1:3]):
            raise ValueError("Driver rejected the requested RS-485 timing or RTS polarity")
    except (OSError, ValueError):
        fcntl.ioctl(fd, SET_RS485, before, True)
        raise
    return f"RS-485 {mode}; flags={actual[0]:#x}"


def header_ttys():
    base = Path("/sys/firmware/devicetree/base")
    if board_name(base) == "h618":
        return {name: (p, uart.header_pins(p, "uart"+str(uart.NODES[p.name])) and (p/DE_PROP).is_file())
                for name,p in uart.ports().items() if "uart"+str(uart.NODES[p.name]) in uart.ROUTES}
    result = {}
    for path in Path("/sys/class/tty").glob("ttyS[0-9]*"):
        match = a733_uart.identify(path.name)
        if match:
            result[path.name] = (match[1], (match[1]/DE_PROP).is_file())
    return result


def serial_op(name, mode):
    ports = header_ttys()
    if name not in ports:
        raise ValueError("Expected an enabled header tty")
    reason = uart.busy(name) or uart.reserved(name)
    if reason:
        raise uart.PortBusy(reason)
    with uart.profile_lock(name):
        fd = os.open("/dev/"+name, os.O_NOCTTY | os.O_NONBLOCK | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        exclusive = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            flag = array("i",[0])
            fcntl.ioctl(fd, getattr(termios,"TIOCGEXCL",0x80045440), flag, True)
            if flag[0]:
                raise uart.PortBusy("Port held exclusively")
            fcntl.ioctl(fd, termios.TIOCEXCL)
            exclusive = True
            if reason := uart.busy(name,fd) or uart.reserved(name):
                raise uart.PortBusy(reason)
            return rs485(fd,mode,has_de=ports[name][1])
        finally:
            try:
                if exclusive:
                    fcntl.ioctl(fd,termios.TIOCNXCL)
            finally:
                os.close(fd)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="bus", required=True)
    i2c = sub.add_parser("i2c")
    i2c.add_argument("op",choices=("list","status","recover")); i2c.add_argument("name",nargs="?")
    tty = sub.add_parser("rs485")
    tty.add_argument("op",choices=("list","status","high","low","off")); tty.add_argument("name",nargs="?")
    args = cli.parse_args()
    if args.op == "list":
        names = adapters(Path("/sys")) if args.bus=="i2c" else header_ttys()
        for name in sorted(names):
            print(name)
    elif args.bus=="i2c":
        print(recovery(args.name,args.op=="recover"))
    else:
        print(serial_op(args.name,args.op))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
