"""Compose and inspect header bus settings on the Armbian Zero 3W vendor DT."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from dt_clock_overlay import install_blob, tokens, write_selection
from uart_routes import cells, enabled, owners, read_tree, strings

BASE = "allwinner/sun60i-a733-orangepi-zero3w.dtb"
SOC = "/soc@3000000/"
PIO = SOC + "pinctrl@2000000"
R_PIO = SOC + "pinctrl@7025000"
CAMERA = SOC + "vind@5800800"
PREFIX = "opi-a733-"
# Port, DT node, mux function, pins in vendor order, physical header pins in that order.
ROUTES = {
    "spi2": ("spi@2542000", "spi2", "PB0 PB1 PB2 PB3", "11/13/5/3"),
    "spi3": ("spi@2543000", "spi3", "PE1 PE2 PE3 PE4 PE0", "23/19/21/26/24"),
    "i2c0": ("twi@2510000", "twi0", "PB2 PB3", "5/3"),
    "i2c1": ("twi@2511000", "twi1", "PB7 PB8", "40/38"),
    "i2c2": ("twi@2512000", "twi2", "PE1 PE2", "23/19"),
    "i2c3": ("twi@2513000", "twi3", "PE3 PE4", "21/26"),
    "uart2": ("uart@2502000", "uart2", "PB0 PB1", "11/13"),
    "uart6": ("uart@2506000", "uart6", "PE0 PE1", "24/23"),
    "uart7": ("uart@7080000", "s_uart0", "PL2 PL3", "16/18"),
}
COMPAT = {"spi": "allwinner,sunxi-spi-v1.3", "i2c": "allwinner,sunxi-twi-v101", "uart": "allwinner,uart-v100"}


def board(nodes):
    compat = strings(nodes["/"].get("compatible", b""))
    if not {"xunlong,orangepi-zero3w", "arm,sun60iw2p1"} <= set(compat):
        raise ValueError("Expected the Armbian Orange Pi Zero 3W A733 DTB")


def spi_parameters(values):
    if (len(values) != 2 or not re.fullmatch(r"[1-9][0-9]{0,8}", values[0])
            or not 187_500 <= int(values[0]) <= 100_000_000 or values[1] not in ("0","1","2","3")):
        raise ValueError("Use device maximum Hz (187500..100000000) and SPI mode (0..3)")
    return tuple(map(int,values))


def spi2_client(nodes):
    path = SOC + ROUTES["spi2"][0]
    candidates = [(node, props) for node, props in nodes.items()
                  if node.rpartition("/")[0] == path and cells(props.get("reg", b"")) == [0]
                  and props.get("status", b"okay\0") in (b"ok\0", b"okay\0")]
    if len(candidates) != 1:
        raise ValueError("SPI2 requires exactly one declared CS0 peripheral")
    node, props = candidates[0]
    if not props.get("compatible") or not re.fullmatch(r"[A-Za-z0-9,._+-]+@0", node.rpartition("/")[2]):
        raise ValueError("Unknown SPI2 peripheral binding")
    cap, = cells(props["spi-max-frequency"])
    return node, cap


def selection(key, values):
    if key == "camera":
        if values != ["release"]:
            raise ValueError("camera release disables vendor camera capture at next boot")
        return CAMERA, 'status = "disabled";', {}
    if key in ("spi2-cs0","spi3-cs0","spi3-cs1"):
        hz, mode = spi_parameters(values[:2])
        flags = ("spi-cpha;" if mode & 1 else "") + (" spi-cpol;" if mode & 2 else "")
        edit = f"spi-max-frequency = <{hz}>; {flags}"
        if key == "spi2-cs0":
            if len(values) != 3:
                raise ValueError("Missing SPI2 client identity")
            child = bytes.fromhex(values[2]).decode("ascii")
            if not re.fullmatch(r"[A-Za-z0-9,._+-]+@0", child):
                raise ValueError("Invalid SPI2 client name")
            return SOC + ROUTES["spi2"][0] + "/" + child, edit, {}
        if len(values) != 2:
            raise ValueError("Unexpected SPI3 parameters")
        return SOC + ROUTES["spi3"][0], 'status = "okay";', {"spidev@" + key[-1]: edit}
    if key not in ROUTES or key == "spi3":
        raise ValueError("Unknown A733 header port")
    props = 'status = "okay";'
    if key.startswith("i2c"):
        if values not in (["100000"], ["400000"]):
            raise ValueError("Supported A733 TWI bus rates: 100000 or 400000 Hz")
        props += f" clock-frequency = <{values[0]}>;"
    elif values != ["on"]:
        raise ValueError("Use on to enable the header route")
    return SOC + ROUTES[key][0], props, {}


def overlay(key, values):
    path, props, children = selection(key, values)
    if key == "spi2":
        # The vendor DT supplies a controller, but no header pinctrl or client.
        source = f'''/dts-v1/; /plugin/; / {{
            fragment@0 {{ target-path = "{PIO}"; __overlay__ {{
                a733_spi2: opi-spi2-pins {{ pins = "PB0","PB1","PB2","PB3"; function = "spi2"; }};
                a733_spi2_sleep: opi-spi2-sleep {{ pins = "PB0","PB1","PB2","PB3"; function = "gpio_in"; }};
            }}; }};
            fragment@1 {{ target-path = "{path}"; __overlay__ {{
                status = "okay"; pinctrl-names = "default", "sleep";
                pinctrl-0 = <&a733_spi2>; pinctrl-1 = <&a733_spi2_sleep>;
                sunxi,spi-bus-mode = <1>; sunxi,spi-cs-mode = <0>;
            }}; }};
        }};'''
        return subprocess.check_output(["dtc", "-@", "-I", "dts", "-O", "dtb"], input=source.encode())
    edits = [(path, props)] + [(path + "/" + child, data) for child, data in children.items()]
    source = "/dts-v1/; /plugin/; / {\n" + "\n".join(
        f'fragment@{i} {{ target-path = "{node}"; __overlay__ {{ {data} }}; }};'
        for i, (node, data) in enumerate(edits)) + "\n};"
    return subprocess.check_output(["dtc", "-I", "dts", "-O", "dtb"], input=source.encode())


def decode(name):
    key, sep, raw = name.removeprefix(PREFIX).partition("--")
    if not sep:
        raise ValueError(f"Malformed A733 overlay {name}")
    values = raw.split("-")
    selection(key, values)
    return key, values


def environment(text):
    config = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z0-9_]+", key) or key in config:
            raise ValueError(f"Invalid or duplicate boot variable {key}")
        config[key] = value
    if config.get("fdtfile", BASE) != BASE:
        raise ValueError("Unexpected fdtfile for Orange Pi Zero 3W")
    return config


def compose(root, text, output):
    env = environment(text)
    dt = root / "dtb" / BASE
    board(read_tree(dt))
    stock = dt.parent / "overlay"
    folder = root / "overlay-user"
    prefixes = env.get("overlay_prefix", "").split()
    blobs = []
    names = env.get("overlays", "").split()
    users = tokens(text)
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", n) for n in names + users + prefixes):
        raise ValueError("Malformed boot overlay name or prefix")
    for name in names:
        candidates = [stock / f"{prefix}-{name}.dtbo" for prefix in prefixes] + [stock / (name+".dtbo")]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise ValueError(f"Missing stock overlay {name}")
        blobs.append(path)
    selected = {}
    device_clock = None
    for name in users:
        path = folder / (name + ".dtbo")
        if name.startswith(PREFIX):
            key, values = decode(name)
            if key in selected or path.is_symlink() or path.read_bytes() != overlay(key, values):
                raise ValueError(f"Duplicate or altered A733 overlay {name}")
            selected[key] = values
            if key == "spi2-cs0":
                device_clock = path
        blobs.append(path)
    if device_clock is not None:
        inputs = [b for b in blobs if b != device_clock]
        ref = read_tree(dt)
        if inputs:
            subprocess.run(["fdtoverlay", "-i", dt, "-o", output, *inputs], check=True)
            ref = read_tree(output)
        node, limit = spi2_client(ref)
        hz, _, device_name = selected["spi2-cs0"]
        if (not enabled(ref, node) or int(hz) > limit or node.rpartition("/")[2].encode().hex() != device_name):
            raise ValueError("Base SPI2 client or peripheral ceiling changed")
    if blobs:
        subprocess.run(["fdtoverlay", "-i", dt, "-o", output, *blobs], check=True)
        nodes = read_tree(output)
    else:
        nodes = read_tree(dt)
    board(nodes)
    return nodes, selected


def verify(nodes, selected, *, report=False):
    handles = {p["phandle"]: (path,p) for path,p in nodes.items() if "phandle" in p}
    claims = owners(nodes, PIO) | owners(nodes, R_PIO, 11)
    rows = []
    for name, (node, function, pins, physical) in ROUTES.items():
        path = SOC + node
        props = nodes[path]
        kind = re.sub(r"[0-9]+$", "", name) if not name.startswith("i2c") else "i2c"
        if COMPAT[kind] not in strings(props["compatible"]):
            raise ValueError(f"Unexpected controller at {path}")
        is_on = enabled(nodes, path)
        if kind == "spi" and is_on:
            count = 2 if name == "spi3" else 1
            if (cells(props.get("sunxi,spi-num-cs", b"")) != [count]
                    or cells(props.get("sunxi,spi-bus-mode", b"")) != [1]
                    or cells(props.get("sunxi,spi-cs-mode", b"")) != [0]
                    or cells(props.get("#address-cells", b"")) != [1]
                    or cells(props.get("#size-cells", b"")) != [0]
                    or any(cells(props.get("cs-gpios", b"")))):
                raise ValueError(f"Expected native master chip selects at {path}")
            claimed_cs = set()
            for child, endpoint in nodes.items():
                if child.rpartition("/")[0] == path and "reg" in endpoint and enabled(nodes, child):
                    cs, = cells(endpoint["reg"])
                    if cs >= count or cs in claimed_cs:
                        raise ValueError(f"Duplicate or invalid chip select at {child}")
                    claimed_cs.add(cs)
        detail = ""
        if kind == "i2c":
            hz, = cells(props["clock-frequency"])
            detail = f"{hz} Hz"
            if name in selected and hz != int(selected[name][0]):
                raise ValueError(f"Overridden SCL at {path}")
        elif name == "spi2":
            detail = "CS0; peripheral supplied by device overlay"
            if "spi2-cs0" in selected:
                child, hz = spi2_client(nodes)
                values = selected["spi2-cs0"]
                ep = nodes[child]
                mode = int("spi-cpha" in ep) + 2 * int("spi-cpol" in ep)
                if (not is_on or child.rpartition("/")[2].encode().hex() != values[2]
                        or (hz,mode) != spi_parameters(values[:2])):
                    raise ValueError("SPI2 client, mode or clock changed")
                detail = f"{child.rpartition('/')[2]} {hz} Hz mode {mode}"
        elif kind == "spi":
            descriptions = []
            for cs in range(2):
                child = path + f"/spidev@{cs}"
                ep = nodes[child]
                hz, = cells(ep["spi-max-frequency"])
                mode = int("spi-cpha" in ep) + 2 * int("spi-cpol" in ep)
                key = f"spi3-cs{cs}"
                if key in selected and (not enabled(nodes, child) or cells(ep["reg"]) != [cs]
                        or strings(ep["compatible"]) != ["rohm,dh2228fv"]
                        or (hz, mode) != tuple(map(int, selected[key]))):
                    raise ValueError(f"Unexpected endpoint or overridden SPI settings at {child}")
                descriptions.append(f"CS{cs} {hz} Hz mode {mode}")
            detail = ", ".join(descriptions)
        if is_on:
            group_root = R_PIO if name == "uart7" else PIO
            for index, allowed in (("0", {function}), ("1", {"io_disabled", "gpio_in"})):
                groups = [handles[h.to_bytes(4,"big")] for h in cells(props["pinctrl-"+index])]
                actual = []
                for group, data in groups:
                    if group.rpartition("/")[0] != group_root or strings(data["function"])[0] not in allowed:
                        raise ValueError(f"Unexpected pinmux for {name}")
                    actual.extend(strings(data["pins"]))
                if sorted(actual) != sorted(pins.split()):
                    raise ValueError(f"Header route changed for {name}")
            for pin in pins.split():
                other = claims.get(pin, set()) - {path}
                if other:
                    message = f"{pin} also claimed by {', '.join(sorted(other))}"
                    if not report:
                        raise ValueError(f"{name}: {message}")
                    detail += "  conflict: " + message
        elif name in selected:
            raise ValueError(f"Managed route disabled: {name}")
        rows.append(f"{name}\t{'enabled' if is_on else 'disabled'}  pins {physical}  {detail}")
    if "camera" in selected and (enabled(nodes, CAMERA) or "allwinner,sunxi-vin-media" not in strings(nodes[CAMERA]["compatible"])):
        raise ValueError("Camera route release was overridden")
    return rows


def divider_grid(route, parent):
    if not 0 < parent <= 4_000_000_000 or route not in ROUTES:
        raise ValueError("Supply a header route and its parent clock in Hz")
    if route.startswith("spi"):
        # CCU M and N both use five-bit linear dividers on A733 SPI3.
        for m in range(32):
            for n in range(32):
                hz = parent // ((m + 1) * (n + 1))
                if 187_500 <= hz <= 100_000_000:
                    yield hz, f"M={m} N={n}"
    elif route.startswith("i2c"):
        for m in range(16):
            for n in range(8):
                for duty in ((10, 11) if m == 0 else (10,)):
                    hz = parent // ((m + 1) * (1 << n) * duty)
                    if 0 < hz <= 400_000:
                        yield hz, f"M={m} N={n} sampling-divisor={duty}"
    else:
        for baud in (1200,2400,4800,9600,19200,38400,57600,115200,230400,460800,921600,1000000,1500000,2000000,3000000,4000000):
            divisor = (parent + 8 * baud) // (16 * baud)
            if 1 <= divisor <= 65535:
                yield parent // (16 * divisor), f"request={baud} DLL/DLH={divisor}"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("root", type=Path)
    cli.add_argument("env", type=Path)
    cli.add_argument("action", choices=("list","set","default","verify","grid"))
    cli.add_argument("args", nargs="*")
    a = cli.parse_args()
    if a.action == "grid":
        port, parent = a.args
        for hz, params in sorted(divider_grid(port, int(parent)), reverse=True):
            print(f"{hz} Hz  {params}")
        return
    root = a.root
    before = a.env.read_text()
    with tempfile.TemporaryDirectory() as work:
        dt = Path(work)/"composed.dtb"
        nodes, saved = compose(root, before, dt)
        if a.action in ("list","verify"):
            for row in verify(nodes, saved, report=a.action == "list"):
                print(row)
            return
        key, *values, output = a.args
        if key not in {"camera", "spi2-cs0", "spi3-cs0", "spi3-cs1", *ROUTES} or key == "spi3":
            raise ValueError("Unknown configurable route")
        names = [n for n in tokens(before) if not n.startswith(PREFIX + key + "--")]
        if a.action == "set":
            if key == "spi2-cs0":
                hz, _ = spi_parameters(values)
                clean = Path(work)/"without-device-clock"
                write_selection(before, clean, names)
                baseline, _ = compose(root, clean.read_text(), dt)
                child, cap = spi2_client(baseline)
                if not enabled(baseline, child) or hz > cap:
                    raise ValueError(f"Enable SPI2 first; its declared CS0 limit is {cap} Hz")
                values.append(child.rpartition("/")[2].encode().hex())
            data = overlay(key, values)
            name = PREFIX + key + "--" + "-".join(values)
            install_blob(root/"overlay-user", name, data)
            names.append(name)
        elif values:
            raise ValueError("default takes only a route")
        after = Path(output)
        write_selection(before, after, names)
        verify(*compose(root, after.read_text(), dt))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
