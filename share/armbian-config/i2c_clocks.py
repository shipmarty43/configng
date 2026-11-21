"""Whole-bus TWI clock selection for the H616 controller on Zero 2W."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

from dt_clock_overlay import check_overlay, install_overlay, prop, tokens, write_selection

BUSES = {f"twi{i}": f"/soc/i2c@{0x5002000 + 0x400*i:x}" for i in range(5)}
BUSES["s-twi0"] = "/soc/i2c@7081400"
PREFIX = "opi-twi-clock-"
TOKEN = re.compile(r"opi-twi-clock-(twi[0-4]|s-twi0)-([1-9][0-9]{0,5})")
MAX = 400_000
DEFAULT = 100_000


def rates(parent):
    # mv64xxx_find_baud_factors iterates N first and keeps the first tie.
    grid = {}
    for n in range(8):
        for m in range(16):
            hz = parent // (10 * (m + 1) * (1 << n))
            if 0 < hz <= MAX:
                grid.setdefault(hz, (m, n))
    return grid


def clock(bus, sysroot=Path("/sys")):
    name = "r-apb2-i2c" if bus == "s-twi0" else "bus-i2c" + bus[-1]
    try:
        parent = int((sysroot/"kernel/debug/clk"/name/"clk_rate").read_text())
        if parent > 0:
            return parent, "live " + name
    except (OSError, ValueError):
        pass
    return 24_000_000, "manual example; input clock unavailable"


def choice(value, grid):
    if not re.fullmatch(r"[0-9]{1,6}", str(value)) or not 0 < int(value) <= MAX:
        raise ValueError("TWI request must be a positive integer up to 400000 Hz")
    hz = max((rate for rate in grid if rate <= int(value)), default=0)
    if not hz:
        raise ValueError("No divider reaches that low a rate at the displayed input clock")
    return hz, *grid[hz]


def enabled(blob, node):
    return prop(blob, node, "status", default="okay") in ("ok", "okay")


def bus_info(blob, bus):
    path = BUSES[bus]
    if "xunlong,orangepi-zero2w" not in prop(blob, "/", "compatible").split():
        raise ValueError("Expected a Zero 2W DTB")
    if "allwinner,sun6i-a31-i2c" not in prop(blob, path, "compatible").split():
        raise ValueError(f"Unexpected controller at {path}")
    active = enabled(blob, path)
    raw = prop(blob, path, "clock-frequency", "u", str(DEFAULT))
    if not raw.isdecimal() or not int(raw):
        raise ValueError(f"Invalid clock-frequency at {path}")
    devices = []
    for node in subprocess.check_output(["fdtget", "-l", blob, path], text=True).splitlines():
        child = path + "/" + node
        if "@" in node and enabled(blob, child):
            devices.append(prop(blob, child, "compatible", default=node) + " @" + node.split("@")[-1])
    return active, int(raw), ", ".join(devices) or "no DT clients"


def selections(names):
    result = {}
    for name in names:
        if name.startswith(PREFIX):
            match = TOKEN.fullmatch(name)
            if not match or match[1] in result or int(match[2]) > MAX:
                raise ValueError(f"Invalid or duplicate TWI override: {name}")
            result[match[1]] = (name, int(match[2]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("env", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    check = sub.add_parser("verify")
    check.add_argument("effective", type=Path)
    check.add_argument("folder", type=Path)
    reset = sub.add_parser("default-all")
    reset.add_argument("after", type=Path)
    for action in ("status", "grid", "set", "default"):
        cmd = sub.add_parser(action)
        cmd.add_argument("bus", choices=BUSES)
        if action == "set":
            cmd.add_argument("hz")
        if action in ("set", "default"):
            cmd.add_argument("after", type=Path)
            cmd.add_argument("folder", type=Path)
    args = parser.parse_args()
    text = args.env.read_text()
    names = tokens(text)
    if args.action == "default-all":
        write_selection(text, args.after, [name for name in names if not name.startswith(PREFIX)])
        return
    saved = selections(names)
    if args.action == "verify":
        for bus, (name, hz) in saved.items():
            path = BUSES[bus]
            if not bus_info(args.baseline, bus)[0] or bus_info(args.effective, bus)[:2] != (True, hz):
                raise ValueError(f"{bus} clock lost its enabled controller or was overridden")
            check_overlay(args.folder / (name + ".dtbo"), path, {"clock-frequency": hz})
        return
    if args.action == "list":
        for bus in BUSES:
            active, default, clients = bus_info(args.baseline, bus)
            print(f"{bus}\t{'enabled' if active else 'disabled'}; {saved.get(bus, ('', default))[1]} Hz; {clients}")
        return
    bus = args.bus
    path = BUSES[bus]
    previous, request = saved.get(bus, (None, None))
    if args.action == "default":
        write_selection(text, args.after, [name for name in names if name != previous])
        return
    active, default, clients = bus_info(args.baseline, bus)
    fin, source = clock(bus)
    grid = rates(fin)
    if args.action == "status":
        live = Path("/sys/firmware/devicetree/base") / path.lstrip("/")
        live_status = "unavailable"
        if live.is_dir():
            state = live / "status"
            if not state.exists() or state.read_bytes().rstrip(b"\0") in (b"okay", b"ok"):
                cell = live / "clock-frequency"
                live_status = f"{int.from_bytes(cell.read_bytes(), 'big') if cell.exists() else DEFAULT} Hz"
            else:
                live_status = "disabled"
        print(f"{bus}: {'enabled' if active else 'disabled'}; clients: {clients}\n"
              f"Live DT: {live_status}; board/default: {default} Hz; next boot: {request or default} Hz\n"
              f"Clock input: {fin} Hz ({source})")
        hz, m, n = choice(request or default, grid)
        print(f"Calculated SCL: {hz} Hz (M={m}, N={n})")
        if "dfrobot,dfr0528" in clients:
            print("DFR0528 MCU: vendor bus-speed limit unspecified; 400 kHz tested on the model only.")
        if bus == "s-twi0":
            print("Standby-domain bus; the stock board uses it for its PMIC.")
    elif args.action == "grid":
        print(f"{fin} Hz input ({source}); request Hz / calculated SCL")
        for hz, (m, n) in sorted(grid.items(), reverse=True):
            print(f"{hz}\t{hz} Hz  M={m} N={n}")
    else:
        if not active:
            raise ValueError(f"{bus} is disabled; select the appropriate pinmux overlay first")
        hz, m, n = choice(args.hz, grid)
        request = int(args.hz)
        name = f"{PREFIX}{bus}-{request}"
        install_overlay(args.folder, name, path, {"clock-frequency": request})
        updated = [name if item == previous else item for item in names] if previous else [*names, name]
        write_selection(text, args.after, updated)
        print(f"{bus}: requested {request} Hz, calculated {hz} Hz (M={m}, N={n}; {source})")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
