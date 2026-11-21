"""Next-boot electrical defaults for the 40-pin Orange Pi Zero 2W and Zero 3W headers."""
import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess
import sys

from dt_clock_overlay import install_blob, tokens, write_selection
from uart_routes import cells, enabled, owners, read_tree, strings

PHYSICAL = (3,5,7,8,10,11,12,13,15,16,18,19,21,22,23,24,26,27,28,29,31,32,33,35,36,37,38,40)
PADS = {
    "h618": dict(zip(PHYSICAL, "PI8 PI7 PI13 PH0 PH1 PH2 PI1 PH3 PI5 PI14 PH4 PH7 PH8 PI6 PH6 PH5 PH9 PI10 PI9 PI0 PI15 PI11 PI12 PI2 PC12 PI16 PI4 PI3".split(), strict=True)),
    "a733": dict(zip(PHYSICAL, "PB3 PB2 PB4 PB9 PB10 PB0 PB5 PB1 PE11 PL2 PL3 PE2 PE3 PD0 PE1 PE0 PE4 PL5 PL4 PE12 PE13 PD1 PD3 PB6 PD2 PD4 PB8 PB7".split(), strict=True)),
}
BOARD = {"h618": ("xunlong,orangepi-zero2w","allwinner,sun50i-h618"),
         "a733": ("xunlong,orangepi-zero3w","arm,sun60iw2p1")}
PREFIX = "opi-header-gpio-"
META = "armbian-config,header-pins"
COMPAT = "armbian,header-gpio-preset"
BIAS = {"up": "bias-pull-up", "down": "bias-pull-down", "off": "bias-disable"}


@dataclass(frozen=True)
class Controller:
    path: str
    compatible: str
    symbol: str
    origin: str       # DT GPIO/IRQ specifier bank zero
    irq_banks: str    # driver order of input-debounce cells
    units_per_us: int


MAIN_2W = Controller("/soc/pinctrl@300b000", "allwinner,sun50i-h616-pinctrl", "pio", "A", "ACDEFGHI", 1)
MAIN_3W = Controller("/soc@3000000/pinctrl@2000000", "allwinner,sun60iw2-pinctrl", "pio", "A", "BCDEFGHIJK", 1000)
STANDBY = Controller("/soc@3000000/pinctrl@7025000", "allwinner,sun60iw2-r-pinctrl", "r_pio", "L", "LM", 1000)
CONTROLLERS = {"h618": (MAIN_2W,), "a733": (MAIN_3W, STANDBY)}


def location(board, pin):
    if pin not in PADS[board]:
        raise ValueError(f"Physical pin {pin} is not a GPIO on this header")
    pad = PADS[board][pin]
    ctl = next(c for c in CONTROLLERS[board] if pad[1] in c.irq_banks)
    return pad, ctl, ord(pad[1]) - ord(ctl.origin), int(pad[2:])


@dataclass(frozen=True)
class Setting:
    bias: str
    drive: str
    debounce: str

    def __post_init__(self):
        if self.bias not in (*BIAS, "default"):
            raise ValueError("Bias must be up, down, off or default")
        if self.drive not in ("10","20","30","40","default"):
            raise ValueError("Drive must be 10, 20, 30, 40 mA or default")
        if self.debounce != "default" and not (
            re.fullmatch(r"[1-9][0-9]{0,3}", self.debounce) and int(self.debounce) <= 3906
        ):
            raise ValueError("Bank filter request must be 1..3906 us or default")

    @property
    def electrical(self):
        return self.bias != "default" or self.drive != "default"


def selected_name(text):
    found = [n for n in tokens(text) if n.startswith(PREFIX)]
    if len(found) > 1 or found and not re.fullmatch(PREFIX + r"[0-9a-f]{64}", found[0]):
        raise ValueError("Malformed or duplicate GPIO overlay selection")
    return found[0] if found else None


def saved(text, folder):
    name = selected_name(text)
    if not name:
        return {}
    path = folder / (name + ".dtbo")
    if path.is_symlink() or PREFIX + hashlib.sha256(path.read_bytes()).hexdigest() != name:
        raise ValueError("GPIO overlay checksum or path changed")
    settings = {}
    for row in strings(read_tree(path)["/"][META]):
        pin, bias, drive, debounce = row.split()
        pin = int(pin)
        if pin in settings:
            raise ValueError("Duplicate GPIO pin in overlay")
        settings[pin] = Setting(bias, drive, debounce)
    return settings


def check_board(board, tree):
    if not set(BOARD[board]) <= set(strings(tree["/"]["compatible"])):
        raise ValueError("DTB does not match the selected Orange Pi board")
    for ctl in CONTROLLERS[board]:
        props = tree[ctl.path]
        if (ctl.compatible not in strings(props["compatible"]) or not enabled(tree, ctl.path)
                or cells(props["#gpio-cells"]) != [3]
                or strings(tree["/__symbols__"].get(ctl.symbol, b"")) != [ctl.path]):
            raise ValueError(f"Unexpected GPIO controller or alias: {ctl.path}")


def claims(board, nodes, irq_only=False):
    result = {}
    for ctl in CONTROLLERS[board]:
        result.update(owners(nodes, ctl.path, ord(ctl.origin)-65, irq_only=irq_only))
    # The A733 vendor UART0 default state has empty pin names. CPU debug on
    # the header is routed by firmware even when Linux pinctrl has no group.
    debug = "/soc@3000000/uart@2500000"
    if not irq_only and board == "a733" and debug in nodes and enabled(nodes, debug):
        for pad in ("PB9","PB10"):
            result.setdefault(pad,set()).add(debug)
    return result


def bank_vector(nodes, ctl):
    props = nodes[ctl.path]
    names = strings(props.get("clock-names", b""))
    handles = {p["phandle"]: p for p in nodes.values() if "phandle" in p}
    clocks = cells(props.get("clocks", b""))
    count = 0
    while clocks:
        provider = handles.get(clocks[0].to_bytes(4, "big"))
        if not provider or "#clock-cells" not in provider:
            raise ValueError("Unresolved GPIO clock provider")
        width, = cells(provider["#clock-cells"])
        if len(clocks) < width + 1:
            raise ValueError("Incomplete GPIO clock specifier")
        clocks = clocks[width+1:]
        count += 1
    if (not {"hosc","losc"} <= set(names) or count != len(names)
            or (count != 3 if ctl == MAIN_2W else count < 3)):
        raise ValueError(f"{ctl.path}: kernel debounce clocks unavailable")
    # Both reference DTs describe their parent GIC using three interrupt cells.
    if ("interrupt-controller" not in props or cells(props.get("#interrupt-cells", b"")) != [3]
            or len(cells(props.get("interrupts", b""))) != 3 * len(ctl.irq_banks)):
        raise ValueError(f"{ctl.path}: unsupported IRQ bank layout")
    vector = cells(props["input-debounce"]) if "input-debounce" in props else [0] * len(ctl.irq_banks)
    if len(vector) != len(ctl.irq_banks):
        raise ValueError(f"{ctl.path}: unexpected input-debounce array length")
    return vector


def compile_profile(board, nodes, settings):
    check_board(board, nodes)
    occupied = claims(board, nodes)
    interrupts = claims(board, nodes, irq_only=True)
    vectors, periods, children, records = {}, {}, [], []
    for pin, setting in sorted(settings.items()):
        pad, ctl, bank, line = location(board, pin)
        if occupied.get(pad):
            raise ValueError(f"Pin {pin} ({pad}) claimed by " + ", ".join(sorted(occupied[pad])))
        if node_path(pin) in nodes:
            raise ValueError(f"Foreign node at {node_path(pin)}")
        records.append(f'"{pin} {setting.bias} {setting.drive} {setting.debounce}"')
        if setting.electrical:
            props = [f'compatible = "{COMPAT}";', f'target-gpios = <&{ctl.symbol} {bank} {line} 0>;']
            if setting.bias in BIAS:
                props.append(BIAS[setting.bias] + ";")
            if setting.drive != "default":
                props.append(f"drive-strength = <{setting.drive}>;")
            children.append(f'{node_path(pin)[1:]} {{ {" ".join(props)} }};')
        if setting.debounce == "default":
            continue
        letter = pad[1]
        usec = int(setting.debounce)
        if periods.setdefault((ctl, letter), usec) != usec:
            raise ValueError(f"P{letter} has one IRQ filter; conflicting debounce periods")
        if ctl not in vectors:
            vectors[ctl] = bank_vector(nodes, ctl)
        idx = ctl.irq_banks.index(letter)
        value = usec * ctl.units_per_us
        if vectors[ctl][idx] != value:
            foreign = {p for other, paths in interrupts.items() if other.startswith("P"+letter) for p in paths}
            if foreign:
                raise ValueError(f"P{letter} bank filter also affects an IRQ at " + ", ".join(sorted(foreign)))
        vectors[ctl][idx] = value

    edits = [("/", " ".join(children))] if children else []
    edits.extend((ctl.path, "input-debounce = <" + " ".join(map(str,vector)) + ">;")
                 for ctl, vector in vectors.items())
    source = "/dts-v1/; /plugin/; / {\n" + META + " = " + ", ".join(records) + ";\n"
    for i,(path,content) in enumerate(edits):
        source += f'fragment@{i} {{ target-path = "{path}"; __overlay__ {{ {content} }}; }};\n'
    blob = subprocess.check_output(["dtc","-q","-@","-I","dts","-O","dtb"],input=(source+"};").encode())
    return blob, vectors


def node_path(pin):
    return f"/opi-header-gpio-{pin}"


def verify(board, baseline, effective, text, folder):
    settings = saved(text, folder)
    if not settings:
        return
    blob, vectors = compile_profile(board, baseline, settings)
    if PREFIX + hashlib.sha256(blob).hexdigest() != selected_name(text):
        raise ValueError("GPIO profile or underlying bank defaults changed; reselect GPIO settings")
    check_board(board, effective)
    used = claims(board, effective)
    for pin, setting in settings.items():
        pad, ctl, bank, line = location(board, pin)
        path = node_path(pin)
        if setting.electrical:
            expected = {"compatible": COMPAT.encode()+b"\0",
                        "target-gpios": effective[ctl.path]["phandle"] + b"".join(x.to_bytes(4,"big") for x in (bank,line,0))}
            if setting.bias in BIAS:
                expected[BIAS[setting.bias]] = b""
            if setting.drive != "default":
                expected["drive-strength"] = int(setting.drive).to_bytes(4,"big")
            if effective.get(path) != expected or used.get(pad) != {path}:
                raise ValueError(f"{pad}: GPIO preset, binding or pin owner was overridden")
        elif used.get(pad):
            raise ValueError(f"{pad}: GPIO taken by another device")
    for ctl, vector in vectors.items():
        if bank_vector(effective,ctl) != vector:
            raise ValueError(f"{ctl.path}: GPIO bank debounce was overridden")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("strip","list","info","get","set","default","verify","driver-needed"))
    parser.add_argument("board", choices=PADS)
    parser.add_argument("env", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("params", nargs="*")
    args = parser.parse_args()
    text = args.env.read_text()
    name = selected_name(text)
    rest = [n for n in tokens(text) if n != name]
    if args.action == "driver-needed":
        proposed, = args.params
        old = saved(text, args.folder)
        new = saved(Path(proposed).read_text(), args.folder)
        changed = any(s.electrical and (p not in old or (s.bias,s.drive) != (old[p].bias,old[p].drive))
                      for p,s in new.items())
        print("yes" if changed else "no")
        return
    if args.action == "strip":
        output, = args.params
        write_selection(text, Path(output), rest)
        return
    basefile, *params = args.params
    baseline = read_tree(Path(basefile))
    check_board(args.board, baseline)
    settings = saved(text, args.folder)
    if args.action == "verify":
        effective, = params
        verify(args.board, baseline, read_tree(Path(effective)), text, args.folder)
        return
    if args.action == "get":
        pin, = map(int, params)
        location(args.board, pin)
        s = settings.get(pin, Setting("default","default","default"))
        print(s.bias, s.drive, s.debounce)
        return
    if args.action in ("list","info"):
        focus = None
        if args.action == "info":
            focus, = map(int, params)
            location(args.board, focus)
        shared = {PADS[args.board][pin][1]:s.debounce for pin,s in settings.items() if s.debounce != "default"}
        filters = {}
        for controller in CONTROLLERS[args.board]:
            try:
                raw = bank_vector(baseline,controller)
            except ValueError:
                filters[controller] = {}
            else:
                filters[controller] = dict(zip(controller.irq_banks, raw, strict=True))
        occupied = claims(args.board, baseline)
        for pin, pad in PADS[args.board].items():
            if focus is not None and pin != focus:
                continue
            s = settings.get(pin, Setting("default","default","default"))
            _, ctl, _, _ = location(args.board, pin)
            owner = ", ".join(sorted(occupied.get(pad, ()))) or "free in DT"
            bank = pad[1]
            value = filters[ctl].get(bank)
            if bank in shared:
                effective = shared[bank] + " us (shared)"
            elif value is None:
                effective = "unavailable"
            else:
                effective = f"{value / ctl.units_per_us:g} us (DT)" if value else "firmware default"
            print(f"{pin}\t{pad} ({ctl.symbol})  bias={s.bias} drive={s.drive} "
                  f"debounce-us={s.debounce}  P{bank} filter={effective}  {owner}")
            if focus is not None:
                others = [str(p) for p, value in settings.items()
                          if p != pin and PADS[args.board][p][1] == bank and value.debounce != "default"]
                irq = {client for other, clients in claims(args.board, baseline, irq_only=True).items()
                       if other.startswith("P"+bank) for client in clients}
                print("Other saved debounce requests in bank:", ", ".join(others) or "none")
                print("DT IRQ consumers in bank:", ", ".join(sorted(irq)) or "none")
        return
    output, pin, *values = params
    pin = int(pin)
    location(args.board, pin)
    if args.action == "set":
        if len(values) != 3:
            raise ValueError("set requires PIN BIAS DRIVE_MA DEBOUNCE_US")
        setting = Setting(*values)
        if setting == Setting("default","default","default"):
            settings.pop(pin, None)
        else:
            settings[pin] = setting
    elif values:
        raise ValueError("default requires one physical pin")
    else:
        settings.pop(pin, None)
    if settings:
        blob, _ = compile_profile(args.board, baseline, settings)
        name = PREFIX + hashlib.sha256(blob).hexdigest()
        install_blob(args.folder, name, blob)
        rest.append(name)
    write_selection(text, Path(output), rest)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
