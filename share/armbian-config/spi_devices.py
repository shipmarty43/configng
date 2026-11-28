"""Per-chip-select Linux boot clocks for the Zero 2W SPI controllers."""
import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess
import sys

import h616_spi_clock as clock
from dt_clock_overlay import check_overlay, install_overlay, prop, tokens, write_selection

BUSES = {"spi0": "/soc/spi@5010000", "spi1": "/soc/spi@5011000"}
PREFIX = "opi-sclk-"
TOKEN = re.compile(r"opi-sclk-(spi[01])-cs(0|[1-9][0-9]*)-([0-9a-f]{16})-([1-9][0-9]{0,8})")
# Compatible-specific ceilings for explicitly identified peripherals. A generic
# spidev node gives no evidence about which part is connected to the header.
CHIP_LIMIT = {"ti,cc1101": 6_500_000, "nxp,pn532": 5_000_000,
              "nordic,nrf24l01": 8_000_000, "nordic,nrf24l01p": 8_000_000, "semtech,sx1262": 16_000_000}
MARKER = "armbian,spi-clock-request-hz"


@dataclass(frozen=True)
class Endpoint:
    bus: str
    cs: int
    path: str
    compatible: str
    board_hz: int

    @property
    def limit(self):
        return min(self.board_hz, clock.MAX_HZ, *(CHIP_LIMIT.get(c, clock.MAX_HZ)
                                                  for c in self.compatible.split()))

    @property
    def sx1262(self):
        return (self.path == BUSES["spi1"] + "/radio@0" and self.cs == 0 and
                {"semtech,sx1262", "armbian,spi-dev"} <= set(self.compatible.split()))

    def token(self, hz):
        identity = hashlib.sha256((self.path + "\n" + self.compatible).encode()).hexdigest()[:16]
        return f"{PREFIX}{self.bus}-cs{self.cs}-{identity}-{hz}"


def endpoints(blob, bus):
    board = prop(blob, "/", "compatible").split()
    if not {"xunlong,orangepi-zero2w", "allwinner,sun50i-h618"} <= set(board):
        raise ValueError("Expected the Orange Pi Zero 2W base DTB")
    ctrl = BUSES[bus]
    if "allwinner,sun50i-h616-spi" not in prop(blob, ctrl, "compatible").split():
        raise ValueError(f"Unexpected controller at {ctrl}")
    result = {}
    if prop(blob, ctrl, "status", default="okay") not in ("ok", "okay"):
        return result
    for child in subprocess.check_output(["fdtget", "-l", blob, ctrl], text=True).splitlines():
        path = f"{ctrl}/{child}"
        if prop(blob, path, "status", default="okay") not in ("ok", "okay"):
            continue
        reg = prop(blob, path, "reg", "u", "-")
        if reg == "-":
            continue  # pinctrl/state metadata
        if not reg.isdecimal() or not re.fullmatch(r"[a-zA-Z0-9,._+\-]+@[0-9a-fA-F]+", child):
            raise ValueError(f"Unsupported SPI addressing at {path}")
        cs = int(reg)
        if cs in result:
            raise ValueError(f"Multiple enabled devices claim {bus} CS{cs}")
        hz = prop(blob, path, "spi-max-frequency", "u", "0")
        compat = prop(blob, path, "compatible", default="")
        if not hz.isdecimal() or not re.fullmatch(r"[A-Za-z0-9_+.,-]+(?: [A-Za-z0-9_+.,-]+)*", compat):
            raise ValueError(f"Invalid SPI device properties at {path}")
        result[cs] = Endpoint(bus, cs, path, compat, int(hz))
    return result


def managed(names):
    result = {}
    for name in names:
        if not name.startswith(PREFIX):
            continue
        match = TOKEN.fullmatch(name)
        if not match:
            raise ValueError(f"Malformed managed SPI overlay: {name}")
        bus, cs, _, hz = match.groups()
        key = (bus, int(cs))
        if key in result:
            raise ValueError(f"Duplicate SPI setting for {bus} CS{cs}")
        result[key] = (name, int(hz))
    return result


def verify(blob, effective, names, folder):
    selected = managed(names)
    buses = {bus for bus, _ in selected}
    baseline = {bus: endpoints(blob, bus) for bus in buses}
    composed = {bus: endpoints(effective, bus) for bus in buses}
    for (bus, cs), (name, hz) in selected.items():
        ep = baseline[bus].get(cs)
        if not ep or name != ep.token(hz) or not clock.MIN_HZ <= hz <= ep.limit or ep.sx1262:
            raise ValueError(f"SPI route changed for {bus} CS{cs}; restore its default first")
        check_overlay(folder / (name + ".dtbo"), ep.path, {"spi-max-frequency": hz, MARKER: hz})
        current = composed[bus].get(cs)
        if (not current or current.path != ep.path or current.compatible != ep.compatible or
                current.board_hz != hz or prop(effective, ep.path, MARKER, "u", "0") != str(hz)):
            raise ValueError(f"SPI setting overridden for {bus} CS{cs}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("env", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    check = sub.add_parser("verify")
    check.add_argument("effective", type=Path)
    check.add_argument("folder", type=Path)
    sub.add_parser("default-all").add_argument("after", type=Path)
    for action in ("list", "status", "grid", "set", "default"):
        cmd = sub.add_parser(action)
        cmd.add_argument("bus", choices=BUSES)
        if action != "list":
            cmd.add_argument("cs", type=int)
        if action == "set":
            cmd.add_argument("hz")
        if action in ("set", "default"):
            cmd.add_argument("after", type=Path)
            cmd.add_argument("folder", type=Path)
    args = parser.parse_args()
    before = args.env.read_text()
    names = tokens(before)
    if args.action == "default-all":
        write_selection(before, args.after, [name for name in names if not name.startswith(PREFIX)])
        return
    saved = managed(names)
    if args.action == "verify":
        verify(args.baseline, args.effective, names, args.folder)
        return
    devices = endpoints(args.baseline, args.bus)
    if args.action == "list":
        for cs in sorted(set(devices) | {cs for bus, cs in saved if bus == args.bus}):
            ep = devices.get(cs)
            description = ep.compatible if ep else "previously configured, route absent"
            if ep and ep.sx1262:
                description += " (SXMD01)"
            print(f"{cs}\t{description}")
        return
    item, hz = saved.get((args.bus, args.cs), (None, None))
    if args.action == "default":
        write_selection(before, args.after, [name for name in names if name != item])
        return
    ep = devices.get(args.cs)
    if not ep:
        raise ValueError(f"No enabled device on {args.bus} CS{args.cs}; use default to clear a stale setting")
    if ep.sx1262:
        raise ValueError("Use SXMD01 for the Waveshare SX1262 clock on SPI1 CS0")
    tree = clock.clock_tree(args.bus)
    if args.action == "status":
        live_node = Path("/sys/firmware/devicetree/base") / ep.path.lstrip("/")
        try:
            present = live_node.joinpath("compatible").read_bytes().rstrip(b"\0").split(b"\0")
            cell = live_node.joinpath("spi-max-frequency").read_bytes() if present == ep.compatible.encode().split() else b""
            live = f"{int.from_bytes(cell, 'big')} Hz" if len(cell) == 4 else "unknown"
        except OSError:
            live = "unavailable"
        print(f"{args.bus.upper()} CS{ep.cs}  {ep.compatible}\nDevice: {ep.path}\n"
              f"Board DT: {ep.board_hz} Hz  Request limit: {ep.limit} Hz\n"
              f"Live DT: {live}  Next boot: {hz or ep.board_hz} Hz"
              + (" (board default)" if hz is None else " (configured)"))
        if clock.MIN_HZ <= (hz or ep.board_hz) <= clock.MAX_HZ:
            print(f"Estimated SCLK ({tree.source}): {clock.estimate(tree, hz or ep.board_hz)}")
    elif args.action == "grid":
        print(f"{args.bus.upper()} CS{ep.cs} | {tree.source} | MCLK {tree.mclk} Hz")
        for request, result in reversed(list(tree.requests(ep.limit))):
            if clock.MIN_HZ * result.divider <= result.mclk <= request * result.divider:
                print(f"{request}\t{result.label(request)}")
    else:
        if not re.fullmatch(r"[0-9]{1,9}", args.hz) or not clock.MIN_HZ <= int(args.hz) <= ep.limit:
            raise ValueError(f"Request must be within {clock.MIN_HZ}..{ep.limit} Hz")
        rate = int(args.hz)
        install_overlay(args.folder, ep.token(rate), ep.path, {"spi-max-frequency": rate, MARKER: rate})
        token = ep.token(rate)
        updated = [token if name == item else name for name in names] if item else [*names, token]
        write_selection(before, args.after, updated)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
