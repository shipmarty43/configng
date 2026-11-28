"""Boot profiles for header PWM and the board's thermal cooling device."""
import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys

from dt_clock_overlay import install_blob, tokens, write_selection
from header_gpio import BOARD, CONTROLLERS, claims
from pwm_routes import CTRL, PINS, channel_node, routed_pin
from uart_routes import cells, enabled, read_tree, strings

PREFIX = "opi-pwmx-"
MARK = "armbian-config,pwm-profile"
COUNT = "armbian,pulse-count"
SOC = "/soc@3000000"
MAIN = SOC + "/pwm@2527000"
STANDBY = SOC + "/pwm@7023000"
FAN = SOC + "/pwm-fan"
# Vendor pinctrl active routes on the shipped Zero 3W DTB.
A733 = {0: "PB4", 1: "PD1", 2: "PD2", 3: "PD3", 4: "PD4", 8: "PB6", 9: "PB7", 22: "PL4"}


@dataclass(frozen=True)
class Profile:
    board: str
    mode: str
    first: int
    values: tuple

    def __post_init__(self):
        board, mode, n, values = self.board, self.mode, self.first, self.values
        if mode == "fan":
            if (board != "a733" or n != 5 or len(values) != 5 or values[0] != 0 or values[-1] != 255
                    or any(b <= a for a, b in zip(values, values[1:]))):
                raise ValueError("Supply five increasing fan levels, starting at 0 and ending at 255")
        elif mode == "pair":
            if n not in {"h618": (2,), "a733": (0, 2, 8)}.get(board, ()):
                raise ValueError("No complete header pair at this starting channel")
            if len(values) != 1 or not 42 <= values[0] <= 10666:
                raise ValueError("Dead time must give 1..255 whole ticks at 24 MHz (42..10666 ns)")
        elif board == "a733" and n in A733 and mode in ("capture", "burst"):
            if mode == "burst" and (len(values) != 1 or not 1 <= values[0] <= 65536):
                raise ValueError("Finite burst count must be 1..65536")
            if mode == "capture" and values:
                raise ValueError("Capture takes no count")
        else:
            raise ValueError("The board driver has no such header PWM mode")

    @property
    def channels(self):
        return (self.first, self.first + 1) if self.mode == "pair" else (self.first,)

    @property
    def name(self):
        return PREFIX + "-".join(map(str, (self.board, self.mode, self.first, *self.values)))

    def properties(self):
        if self.mode == "fan":
            return {FAN: {"cooling-levels": self.values}}
        props = {}
        for ch in self.channels:
            fields = {"status": "okay", MARK: self.name}
            if self.mode == "pair":
                fields.update(bind_pwm=(ch ^ 1,), dead_time=self.values)
            if self.mode == "burst":
                fields[COUNT] = self.values
            props[channel(self.board, ch)] = fields
        return props

    def blob(self):
        source = "/dts-v1/; /plugin/;\n"
        for path, fields in self.properties().items():
            lines = []
            for key, value in fields.items():
                data = f'"{value}"' if isinstance(value, str) else "<" + " ".join(map(str, value)) + ">"
                lines.append(f"{key} = {data};")
            source += f'&{{{path}}} {{ {" ".join(lines)} }};\n'
        return subprocess.check_output(["dtc", "-q", "-I", "dts", "-O", "dtb"], input=source.encode())


def decode(name):
    board, mode, *nums = name.removeprefix(PREFIX).split("-")
    if not nums or not all(re.fullmatch(r"0|[1-9][0-9]{0,4}", x) for x in nums):
        raise ValueError("Malformed PWM profile name")
    profile = Profile(board, mode, int(nums[0]), tuple(map(int, nums[1:])))
    if profile.name != name:
        raise ValueError("Unknown PWM profile")
    return profile


def channel(board, ch):
    if board == "h618":
        return channel_node(ch)
    return SOC + ("/s_pwm0@7023012" if ch == 22 else f"/pwm0@252701{ch:x}")


def controller(board, ch):
    if board == "h618":
        return CTRL
    return STANDBY if ch == 22 else MAIN


def consumers(nodes, ctrl):
    """Resolve variable-width PWM specifiers, including non-header consumers."""
    handles = {p["phandle"]: p for p in nodes.values() if "phandle" in p}
    result = {}
    for path, p in nodes.items():
        if "pwms" not in p or not enabled(nodes, path):
            continue
        spec = cells(p["pwms"])
        while spec:
            handle = spec[0].to_bytes(4, "big")
            width, = cells(handles[handle]["#pwm-cells"])
            if not 1 <= width < len(spec):
                raise ValueError("Malformed PWM consumer at " + path)
            if handle == nodes[ctrl]["phandle"]:
                result.setdefault(spec[1], set()).add(path)
            spec = spec[1 + width:]
    return result


def a733_mux_pin(nodes, ch):
    """Verify both BSP pinctrl states without starting or selecting a PWM mode."""
    d = nodes[channel("a733", ch)]
    pin = A733[ch]
    ctl = CONTROLLERS["a733"][int(ch == 22)].path
    groups = [g for k, g in nodes.items() if k.rpartition("/")[0] == ctl and
              g.get("phandle") == d.get("pinctrl-0") and "phandle" in g]
    function = "s_pwm0_2" if ch == 22 else f"pwm0_{ch}"
    if (strings(d["pinctrl-names"]) != ["active", "sleep"] or len(groups) != 1 or
            strings(groups[0]["pins"]) != [pin] or strings(groups[0]["function"]) != [function]):
        raise ValueError(f"Unqualified active route for {function}")
    sleeps = [g for k, g in nodes.items() if k.rpartition("/")[0] == ctl and
              "phandle" in g and g["phandle"] == d.get("pinctrl-1")]
    if len(sleeps) != 1 or strings(sleeps[0]["pins"]) != [pin]:
        raise ValueError(f"Unexpected sleep route for {function}")
    return pin


def check(board, nodes, profile, *, applied):
    if not set(BOARD[board]) <= set(strings(nodes["/"]["compatible"])) or profile.board != board:
        raise ValueError("PWM profile and device tree board differ")
    ctrl = controller(board, profile.first)
    p = nodes[ctrl]
    compat = ("allwinner,sun50i-h616-pwm" if board == "h618" else
              "allwinner,sunxi-pwm-v204" if ctrl == STANDBY else "allwinner,sunxi-pwm-v203")
    if not enabled(nodes, ctrl) or compat not in strings(p["compatible"]):
        raise ValueError("Unexpected PWM controller or disabled parent")
    used = consumers(nodes, ctrl)
    if profile.mode == "fan":
        fan = nodes[FAN]
        refs = cells(fan["pwms"])
        if (not enabled(nodes, FAN) or strings(fan["compatible"]) != ["pwm-fan"]
                or refs != [int.from_bytes(p["phandle"], "big"), 5, 25000, 0]
                or used.get(5) != {FAN} or len(cells(fan["cooling-levels"])) != 5):
            raise ValueError("Expected the Zero 3W PWM0-5 thermal fan")
        if applied and cells(fan["cooling-levels"]) != list(profile.values):
            raise ValueError("Final fan curve differs from the saved levels")
        return
    refs = cells(p["sunxi-pwms"])
    if (cells(p["pwm-base"]) != [20 if ctrl == STANDBY else 0] or
            len(refs) != (6 if board == "h618" else 10)):
        raise ValueError("Unexpected PWM channel map")
    if profile.mode == "capture" and not p.get("interrupts"):
        raise ValueError("PWM capture requires a controller IRQ")
    occupied_pins = claims(board, nodes)
    for ch in profile.channels:
        path = channel(board, ch)
        d = nodes[path]
        if refs[ch % 10] != int.from_bytes(d["phandle"], "big"):
            raise ValueError("PWM provider phandle mismatch")
        if used.get(ch % 10) or (profile.mode == "burst" and used.get((ch % 10) ^ 1)):
            raise ValueError("A kernel PWM consumer owns the requested channel or shared output clock")
        if applied and not enabled(nodes, path):
            raise ValueError("PWM route disabled")
        if board == "h618":
            pin = routed_pin(nodes, ch)
            if pin not in PINS[ch]:
                raise ValueError(f"Select the PWM{ch} header route in PWM001 first")
        else:
            pin = a733_mux_pin(nodes, ch)
        conflict = occupied_pins.get(pin, set()) - {path}
        if conflict:
            raise ValueError(f"{pin} already claimed by " + ", ".join(sorted(conflict)))
        expected = profile.properties()[path] if applied else {}
        for key, default in (("bind_pwm", 255), ("dead_time", 0), (COUNT, 0), ("group_channel", 0),
                             ("group_run_count", 0), ("clk_bypass_output", 0)):
            if key in d or key in expected:
                if cells(d.get(key, b"")) != list(expected.get(key, (default,))):
                    raise ValueError(f"Conflicting {key} at {path}")
        if "clk_bypass_osc24m" in d or strings(d.get(MARK, b"")) != ([profile.name] if applied else []):
            raise ValueError("Unexpected PWM profile or clock bypass at " + path)


def saved(board, text, folder):
    result = []
    occupied = set()
    for name in tokens(text):
        if not name.startswith(PREFIX):
            continue
        item = decode(name)
        file = folder / (name + ".dtbo")
        if item.board != board or file.is_symlink() or file.read_bytes() != item.blob():
            raise ValueError("Foreign or altered PWM profile " + name)
        if occupied.intersection(item.channels):
            raise ValueError("Overlapping PWM profiles")
        occupied.update(item.channels)
        result.append(item)
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "verify", "strip", "list"))
    cli.add_argument("board", choices=BOARD)
    cli.add_argument("env", type=Path)
    cli.add_argument("folder", type=Path)
    cli.add_argument("args", nargs="*")
    a = cli.parse_args()
    text = a.env.read_text()
    profiles = saved(a.board, text, a.folder)
    if a.action == "list":
        for item in profiles:
            print(item.name)
    elif a.action == "strip":
        after, = a.args
        write_selection(text, Path(after), [n for n in tokens(text) if not n.startswith(PREFIX)])
    elif a.action == "verify":
        base, dt = map(Path, a.args)
        original, nodes = read_tree(base), read_tree(dt)
        for item in profiles:
            check(a.board, original, item, applied=False)
            check(a.board, nodes, item, applied=True)
    else:
        after, mode, n, *values = a.args
        n = int(n)
        names = tokens(text)
        if mode == "off":
            if values:
                raise ValueError("off takes only the channel number")
            names = [x for x in names if not (x.startswith(PREFIX) and n in decode(x).channels)]
        else:
            item = Profile(a.board, mode, n, tuple(map(int, values)))
            position = len(names)
            for old in profiles:
                if set(old.channels) & set(item.channels):
                    if (old.mode, old.first) != (item.mode, item.first):
                        raise ValueError("Remove the existing channel profile first")
                    position = names.index(old.name)
                    names.pop(position)
            install_blob(a.folder, item.name, item.blob())
            names.insert(position, item.name)
        write_selection(text, Path(after), names)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
