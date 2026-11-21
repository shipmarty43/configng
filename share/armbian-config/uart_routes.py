"""Compose and verify the Zero 2W 40-pin UART routes without accessing a tty."""
import argparse
import ctypes as ct
from pathlib import Path
import re
import struct
import subprocess
import sys

from dt_clock_overlay import install_blob, tokens, write_selection

PIO = "/soc/pinctrl@300b000"
# TX, RX, physical TX/RX, canonical stock overlay.
ROUTES = {
    "uart0": ("PH0", "PH1", "8/10", None),
    "uart2": ("PI5", "PI6", "15/22", "uart2-pi"),
    "uart3": ("PI9", "PI10", "28/27", "uart3-pi"),
    "uart4": ("PI13", "PI14", "7/16", "uart4-pi"),
    "uart5": ("PH2", "PH3", "11/13", "uart5"),
}


def address(port):
    return f"/soc/serial@{0x5000000 + int(port[-1]) * 0x400:x}"


# TX/RX/RTS/CTS in signal order and their physical header positions.
FLOW = {
    ("uart2", "rtscts"): (("PI5", "PI6", "PI7", "PI8"), "15/22/5/3"),
    ("uart2", "rtscts-ph"): (("PH5", "PH6", "PH7", "PH8"), "24/23/19/21"),
    ("uart3", "rtscts"): (("PI9", "PI10", "PI11", "PI12"), "28/27/32/33"),
    ("uart4", "rtscts"): (("PI13", "PI14", "PI15", "PI16"), "7/16/31/37"),
}
FLOW_PROP = "armbian-config,rtscts"
FLOW_CONFLICTS = ("rts-gpios", "cts-gpios", "linux,rs485-enabled-at-boot-time")


def token(port, mode="txrx"):
    base = f"opi-{port}-header"
    return base if mode == "txrx" else f"{base}-{mode}"


def route_pins(port, mode):
    return ROUTES[port][:2] if mode == "txrx" else FLOW[port, mode][0]


def selected_mode(port, names):
    modes = {"txrx", *(mode for name, mode in FLOW if name == port)}
    expected = {token(port, mode): mode for mode in modes}
    selected = [name for name in names if name == token(port) or name.startswith(token(port) + "-")]
    if len(selected) > 1 or selected and selected[0] not in expected:
        raise ValueError(f"Unknown or duplicate header selection for {port}")
    return expected[selected[0]] if selected else None


def strings(raw):
    return raw.rstrip(b"\0").decode("ascii").split("\0") if raw else []


def cells(raw):
    if len(raw) % 4:
        raise ValueError("Unaligned DT property")
    return [n for n, in struct.iter_unpack(">I", raw)]


def read_tree(blob):
    """Read a validated flattened tree using the library installed with dtc."""
    lib = ct.CDLL("libfdt.so.1")
    lib.fdt_check_full.argtypes = (ct.c_void_p, ct.c_size_t)
    lib.fdt_get_name.argtypes = (ct.c_void_p, ct.c_int, ct.POINTER(ct.c_int))
    lib.fdt_get_name.restype = ct.c_char_p
    lib.fdt_getprop_by_offset.argtypes = (ct.c_void_p, ct.c_int, ct.POINTER(ct.c_char_p), ct.POINTER(ct.c_int))
    lib.fdt_getprop_by_offset.restype = ct.c_void_p
    lib.fdt_next_tag.argtypes = (ct.c_void_p, ct.c_int, ct.POINTER(ct.c_int))
    data = blob.read_bytes()
    if lib.fdt_check_full(data, len(data)):
        raise ValueError("Invalid composed DTB")
    nodes, stack = {}, []
    offset = 0
    following, size, key = ct.c_int(), ct.c_int(), ct.c_char_p()
    while True:
        tag = lib.fdt_next_tag(data, offset, ct.byref(following))
        if following.value <= offset:
            raise ValueError("Invalid DT structure offset")
        if tag == 1:  # FDT_BEGIN_NODE
            name = lib.fdt_get_name(data, offset, None).decode("ascii")
            path = stack[-1].rstrip("/") + "/" + name if stack else "/"
            nodes[path] = {}
            stack.append(path)
        elif tag == 2:
            stack.pop()
        elif tag == 3:
            value = lib.fdt_getprop_by_offset(data, offset, ct.byref(key), ct.byref(size))
            nodes[stack[-1]][key.value.decode("ascii")] = ct.string_at(value, size.value)
        elif tag == 9:
            return nodes
        offset = following.value


def enabled(nodes, path):
    while path != "/":
        if nodes[path].get("status", b"okay\0") not in (b"okay\0", b"ok\0"):
            return False
        path = path.rsplit("/", 1)[0] or "/"
    return True


def owners(nodes, pio=PIO, first_bank=0, *, irq_only=False):
    """Resolve pinctrl references and explicit GPIO specifiers from enabled consumers."""
    handles = {p["phandle"]: path for path, p in nodes.items() if "phandle" in p}
    claims = {}
    def claim(pin, owner):
        claims.setdefault(pin, set()).add(owner)

    for path, props in nodes.items():
        if path.startswith("/__") or not enabled(nodes, path):
            continue
        for key, raw in props.items():
            if re.fullmatch(r"pinctrl-[0-9]+", key):
                for handle in cells(raw):
                    group = handles.get(handle.to_bytes(4, "big"))
                    if group and group.rpartition("/")[0] == pio:
                        props_group = nodes[group]
                        function = props_group.get("function", props_group.get("allwinner,function", b""))
                        if irq_only and not set(strings(function)) & {"irq", "eint"}:
                            continue
                        for pin in strings(props_group.get("pins", props_group.get("allwinner,pins", b""))):
                            claim(pin, path)
            elif key in ("interrupts", "interrupts-extended"):
                specs = cells(raw)
                parent = path
                while key == "interrupts" and "interrupt-parent" not in nodes[parent] and parent != "/":
                    parent = parent.rsplit("/",1)[0] or "/"
                inherited = nodes[parent].get("interrupt-parent")
                i = 0
                while i < len(specs):
                    if key == "interrupts-extended":
                        ref = specs[i].to_bytes(4,"big")
                        i += 1
                    else:
                        ref = inherited
                    controller = handles.get(ref)
                    if controller is None:
                        if key == "interrupts-extended":
                            raise ValueError(f"Unknown IRQ provider at {path}")
                        break
                    count, = cells(nodes[controller]["#interrupt-cells"])
                    if not count or i + count > len(specs):
                        raise ValueError(f"Truncated IRQ at {path}")
                    if controller == pio:
                        bank, line = specs[i:i+2]
                        claim(f"P{chr(65+first_bank+bank)}{line}", path)
                    i += count
            elif (key in ("gpio", "gpios") or key.endswith(("-gpios", "-gpio")) or
                  ((key.endswith(("_gpio", "_gpios", "_hostwake", "_pwdn")) or key in ("bt_rst_n", "bt_wake", "wlan_regon"))
                   and len(raw) >= 16 and raw[:4] in handles and "#gpio-cells" in nodes[handles[raw[:4]]])):
                if irq_only:
                    parent = path.rpartition("/")[0] or "/"
                    consumer = strings(props.get("compatible", b"")) + strings(nodes[parent].get("compatible", b""))
                    if not ({"gpio-keys", "pps-gpio"} & set(consumer)
                            or key.replace("_", "-").split(",")[-1].startswith(("irq-", "interrupt-", "int-", "cd-", "wakeup-"))
                            or key.endswith("_hostwake")):
                        continue
                spec = cells(raw)
                if "gpio-hog" in props:
                    if path.rpartition("/")[0] == pio:
                        for i in range(0, len(spec), 3):
                            bank, line, _ = spec[i:i+3]
                            claim(f"P{chr(65+first_bank+bank)}{line}", path)
                    continue
                i = 0
                while i < len(spec):
                    handle = spec[i]
                    i += 1
                    if handle == 0:  # Unused/native chip-select placeholder.
                        continue
                    controller = handles.get(handle.to_bytes(4, "big"))
                    if not controller or "#gpio-cells" not in nodes[controller]:
                        raise ValueError(f"Cannot resolve {key} at {path}")
                    count, = cells(nodes[controller]["#gpio-cells"])
                    if i + count > len(spec):
                        raise ValueError(f"Truncated {key} at {path}")
                    if controller == pio:
                        bank, line, _ = spec[i:i+count]
                        claim(f"P{chr(65+first_bank+bank)}{line}", path)
                    i += count
    return claims


def matches_header(nodes, port, mode="txrx"):
    controller = nodes[address(port)]
    refs = cells(controller.get("pinctrl-0", b""))
    groups = {p["phandle"]: p for path, p in nodes.items()
              if path.rpartition("/")[0] == PIO and "phandle" in p}
    pins = []
    for ref in refs:
        group = groups.get(ref.to_bytes(4, "big"), {})
        if strings(group.get("function", b"")) != [port]:
            return False
        pins += strings(group.get("pins", b""))
    return pins == list(route_pins(port, mode))


def inspect(blob, names):
    nodes = read_tree(blob)
    if not {"xunlong,orangepi-zero2w", "allwinner,sun50i-h618"} <= set(strings(nodes["/"]["compatible"])):
        raise ValueError("Expected the Zero 2W DTB")
    modes = {port: selected_mode(port, names) for port in ROUTES}
    claims = owners(nodes) if any(modes.values()) else {}
    for port, mode in modes.items():
        if mode is None:
            continue
        if port == "uart0":
            raise ValueError(f"Invalid managed route for {port}")
        path = address(port)
        group = PIO + "/opi-" + port + "-header-pins"
        props = nodes.get(group, {})
        if (not enabled(nodes, path) or "snps,dw-apb-uart" not in strings(nodes[path]["compatible"])
                or cells(nodes[path]["reg"]) != [int(path.split("@")[1], 16), 0x400]
                or strings(nodes[path].get("pinctrl-names", b"")) != ["default"]
                or "phandle" not in props or nodes[path].get("pinctrl-0") != props["phandle"]
                or strings(props.get("function", b"")) != [port]
                or strings(props.get("pins", b"")) != list(route_pins(port, mode))):
            raise ValueError(f"{port} controller or header pinmux was overridden")
        if mode != "txrx" and (nodes[path].get(FLOW_PROP) != b"h618\0" or nodes[path].get("uart-has-rtscts") != b""
                               or any(key in nodes[path] for key in FLOW_CONFLICTS)):
            raise ValueError(f"{port}: RTS/CTS capability or restore marker was overridden")
        for pin in route_pins(port, mode):
            foreign = claims.get(pin, set()) - {path}
            if foreign:
                raise ValueError(f"{port}: {pin} already used by " + ", ".join(sorted(foreign)))
    return nodes


def overlay_data(port, mode="txrx"):
    pins = ", ".join(f'"{p}"' for p in route_pins(port, mode))
    flow = f' uart-has-rtscts; {FLOW_PROP} = "h618";' if mode != "txrx" else ""
    # Use a private pin group; some stock DTBs mislabel the UART3/4 groups.
    source = f'''/dts-v1/; /plugin/;
/ {{
    fragment@0 {{ target-path = "{PIO}";
        __overlay__ {{ opi_{port}_header: opi-{port}-header-pins {{ pins = {pins}; function = "{port}"; }}; }};
    }};
    fragment@1 {{ target-path = "{address(port)}";
        __overlay__ {{ pinctrl-names = "default"; pinctrl-0 = <&opi_{port}_header>; status = "okay";{flow} }};
    }};
}};
'''
    return subprocess.check_output(["dtc", "-q", "-@", "-I", "dts", "-O", "dtb"], input=source.encode())


def prepare(before, after, folder, port, action):
    if port == "uart0":
        raise ValueError("UART0 is the base-board serial port; see the console and GNSS menus")
    text = before.read_text()
    names = tokens(text)
    old = selected_mode(port, names)
    mode = action.removeprefix("enable-") if action.startswith("enable-") else "txrx"
    if mode != "txrx" and (port, mode) not in FLOW:
        raise ValueError(f"No {mode} route on the header for {port}")
    matches = re.findall(r"^overlays=([^\n]*)$", text, re.M)
    if len(matches) > 1:
        raise ValueError("Duplicate overlays entry")
    stock = matches[0].split() if matches else []
    canonical = ROUTES[port][3]
    known = {canonical}
    if (port, "rtscts") in FLOW:
        known.add(f"{port}-pi-rts-cts")
    if port == "uart2":
        known.add("uart2-ph-rts-cts")
    alternatives = [n for n in stock if port in n and n not in known]
    if alternatives:
        raise ValueError("Another UART route is selected: " + " ".join(alternatives))
    if known.intersection(stock):
        stock = [n for n in stock if n not in known]
        text = re.sub(r"^overlays=.*$", "overlays=" + " ".join(stock), text, flags=re.M)
    if old is not None and (action == "disable" or old != mode):
        names.remove(token(port, old))
    if action != "disable":
        install_blob(folder, token(port, mode), overlay_data(port, mode))
        if token(port, mode) not in names:
            names.append(token(port, mode))
    write_selection(text, after, names)


def env_content(text):
    assignments, notes = {}, []
    for line in text.splitlines(keepends=True):
        key, equal, _ = line.partition("=")
        if equal and re.fullmatch(r"[A-Za-z0-9_]+", key):
            if key in assignments:
                raise ValueError(f"Cannot roll back reordered environment with duplicate {key}")
            assignments[key] = line
        elif not line.strip() or line.lstrip().startswith("#"):
            notes.append(line)
        else:
            raise ValueError("Unrecognized boot environment line")
    return assignments, notes


def rollback_reordered(before, after, current, output):
    """Armbian re-appends usbstoragequirks at boot. Retain today's ordering."""
    saved, _ = env_content(before.read_text())
    expected = env_content(after.read_text())
    text = current.read_text()
    if env_content(text) != expected:
        raise ValueError("Boot configuration has changed since this backup")
    updated = expected[0]
    changed = {k for k in saved.keys() | updated.keys() if saved.get(k) != updated.get(k)}
    if not changed <= {"overlays", "user_overlays"}:
        raise ValueError("Unexpected keys in the UART backup")
    lines = []
    for line in text.splitlines(keepends=True):
        key = line.partition("=")[0]
        if key in changed:
            if key in saved:
                lines.append(saved[key])
        else:
            lines.append(line)
    lines.extend(line for key, line in saved.items() if key in changed and key not in updated)
    output.write_text("".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="op", required=True)
    for op in ("list", "verify"):
        sub = cmds.add_parser(op)
        sub.add_argument("dtb", type=Path)
        sub.add_argument("env", type=Path)
        if op == "verify":
            sub.add_argument("folder", type=Path)
    undo = cmds.add_parser("rollback-reordered")
    for name in ("before", "after", "current", "output"):
        undo.add_argument(name, type=Path)
    inactive = cmds.add_parser("inactive")
    inactive.add_argument("dtb", type=Path)
    inactive.add_argument("port", choices=ROUTES)
    sub = cmds.add_parser("prepare")
    sub.add_argument("before", type=Path)
    sub.add_argument("after", type=Path)
    sub.add_argument("folder", type=Path)
    sub.add_argument("port", choices=ROUTES)
    sub.add_argument("action", choices=("enable", "enable-rtscts", "enable-rtscts-ph", "disable"))
    args = parser.parse_args()
    if args.op == "rollback-reordered":
        rollback_reordered(args.before, args.after, args.current, args.output)
        return
    if args.op == "prepare":
        prepare(args.before, args.after, args.folder, args.port, args.action)
        return
    if args.op == "inactive":
        if enabled(inspect(args.dtb, []), address(args.port)):
            raise ValueError(f"{args.port} is enabled by another provider; keep or remove that route first")
        return
    text = args.env.read_text()
    names = tokens(text)
    nodes = inspect(args.dtb, names if args.op == "verify" else [])
    if args.op == "verify":
        stock = re.findall(r"^overlays=(.*)$", text, re.M)
        for port in ROUTES:
            mode = selected_mode(port, names)
            if mode is None:
                continue
            if any(port in s for line in stock for s in line.split()):
                raise ValueError(f"Duplicate stock and managed overlays for {port}")
            file = args.folder / (token(port, mode) + ".dtbo")
            if file.is_symlink() or file.read_bytes() != overlay_data(port, mode):
                raise ValueError(f"Unexpected contents of {file.name}")
    if args.op == "list":
        for port, (_, _, pins, stock) in ROUTES.items():
            state = "enabled" if enabled(nodes, address(port)) else "disabled"
            mode = selected_mode(port, names)
            wiring = mode or "txrx"
            if state == "enabled" and not matches_header(nodes, port, wiring):
                wiring = next((variant for name, variant in FLOW if name == port
                               and matches_header(nodes, port, variant)), None)
                if wiring is None:
                    state += "; different or invalid pinmux"
            if stock and any(stock in line.split() for line in re.findall(r"^overlays=(.*)$", text, re.M)):
                state += f"; stock {stock} selected"
            if mode is not None:
                state = "managed, " + state
            signals = "TX/RX " + pins if wiring in (None, "txrx") else "TX/RX/RTS/CTS " + FLOW[port, wiring][1]
            print(f"{port}\t{signals}; {state}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
