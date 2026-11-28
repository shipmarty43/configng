"""Zero 3W BUS002 profiles using the vendor Armbian DT routes."""
from dataclasses import dataclass
from itertools import combinations
import re

import a733_io as io
import header_gpio
import header_panel
import pwm_modes as pwm
from dt_clock_overlay import install_blob, tokens, write_selection
from uart_routes import cells, enabled, strings

PADS = header_gpio.PADS["a733"]
DEBUG = io.SOC + "uart@2500000"
RESERVES = {"camera": io.CAMERA, "pinctrl-test": io.PIN_TEST}
SPI3_CS = {0: ("PE0", 24), 1: ("PE4", 26)}
SPI_SIGNALS = {"spi2": ("CS0", "CLK", "MOSI", "MISO"),
               "spi3": ("CLK", "MOSI", "MISO", "CS1", "CS0")}


@dataclass(frozen=True)
class Route:
    group: str
    port: str
    path: str
    stock: str
    values: tuple
    label: str

    @property
    def provider(self):
        if self.values and self.values != ("stock",):
            return io.PREFIX + self.port + "--" + "-".join(self.values)
        return None


def catalog():
    routes = {}
    def add(group, port, mode, path, stock, values, label):
        routes[f"a733-{port}-{mode}"] = Route(group, port, path, stock, tuple(values), label)
    for port, (node, _, _, physical) in io.ROUTES.items():
        path = io.SOC + node
        stock = {"spi2": "", "spi3": "spi3-cs0-cs1-spidev"}.get(port, port)
        group = "I²C" if port.startswith("i2c") else "UART" if port.startswith("uart") else "SPI"
        label = port.upper().replace("I2C", "I²C")
        if port == "spi2":
            for count in range(4):
                for extra in combinations((1, 2, 3), count):
                    cs = (0, *extra)
                    desc = ", ".join(f"CS{i} ({io.SPI2_CS[i][1]})" for i in cs)
                    add(group, port, "cs"+"".join(map(str, cs)), path, stock,
                        ("on", *map(str, extra)), f"SPI2 · {desc}")
        elif port == "spi3":
            add(group, port, "on", path, stock, ("stock",), "SPI3 · CS0 (24), CS1 (26)")
        elif group == "I²C":
            for hz in (100000, 400000):
                add(group, port, str(hz), path, stock, (str(hz),), f"{label} · {hz//1000} кГц · {physical}")
        else:
            add(group, port, "txrx", path, stock, ("on",), f"{label} TX/RX · {physical}")
            if port in io.UART_FLOW:
                add(group, port, "rtscts", path, stock, ("rtscts",),
                    f"{label} TX/RX/RTS/CTS · {physical}/{io.UART_FLOW[port][1]}")
        add(group, port, "off", path, stock, (), f"{label} · убрать маршрут")
    for n, pad in pwm.A733.items():
        port = f"pwm{n}"
        name = "S_PWM0-2" if n == 22 else f"PWM0-{n}"
        pin = next(pin for pin, item in PADS.items() if item == pad)
        stock = "spwm2" if n == 22 else port
        for mode, values in (("on", ("stock",)), ("off", ())):
            add("PWM", port, mode, pwm.channel("a733", n), stock, values,
                f"{name} · {pad} ({pin}) · " + ("включить" if values else "убрать маршрут"))
    for key, path in RESERVES.items():
        name = "Камера VIN (вывод 24)" if key == "camera" else "Тестовый драйвер PIO (8, 10, 35)"
        for mode, values in (("release", ("release",)), ("default", ())):
            add("Резервы", key, mode, path, "", values,
                name + (" · освободить" if values else " · вернуть штатное назначение"))
    return routes


ROUTES = catalog()

# Only catalogued "off" actions and explicit vendor releases can yield a pin.
RELEASES = {r.port: r for r in ROUTES.values() if
            (r.port in RESERVES and r.values == ("release",)) or (r.port not in RESERVES and not r.values)}


def selection(target):
    key, *ports = target.split("+")
    route = ROUTES.get(key)
    if route is None:
        raise ValueError("INVALID: Неизвестный маршрут гребёнки")
    if not ports:
        return route, ()
    owners = set(ports)
    if (not route.values or route.port in RESERVES or route.port in owners or
            len(ports) != len(owners) or not owners.issubset(RELEASES)):
        raise ValueError("INVALID: Недопустимый список владельцев для этого маршрута")
    return route, tuple(RELEASES[port] for port in sorted(ports))


def transition_label(route, releases):
    names = {"camera": "камеру VIN", "pinctrl-test": "тестовый драйвер PIO"}
    owners = [names.get(r.port, r.port.upper().replace("I2C", "I²C")) for r in releases]
    if len(owners) == 1:
        return f"Отключить {owners[0]} и включить {route.label}"
    owner_list = ", ".join(owners[:-1]) + " и " + owners[-1]
    return f"Отключить {owner_list}, затем включить {route.label}"


def owners_on_route(route, current, candidate):
    pins = {row["pin"] for row in candidate if any(o["path"] == route.path for o in row["owners"])}
    return {o["path"] for row in current if row["pin"] in pins for o in row["owners"] if o["path"] != route.path}


def alternative(key, route, current, candidate):
    if not route.values or route.port in RESERVES:
        return None
    conflicts = owners_on_route(route, candidate, candidate)
    if not conflicts or not conflicts <= owners_on_route(route, current, candidate):
        return None
    ports = sorted(port for port, release in RELEASES.items() if release.path in conflicts)
    releases = [RELEASES[port] for port in ports]
    if {r.path for r in releases} != conflicts:
        return None
    return {"id": "+".join([key, *ports]), "label": transition_label(route, releases)}


def choices():
    return [dict(id=key, group=route.group, label=route.label) for key, route in ROUTES.items()]


def edit(route, before, after, folder, *, strip=False):
    text = before.read_text()
    stock = io.environment(text).get("overlays", "").split()
    # Armbian's stock overlay route is resolved relative to overlay_prefix.
    target_stock = route.stock if not strip and route.values == ("stock",) else None
    aliases = {route.stock, "sun60i-a733-" + route.stock} if route.stock else set()
    existing = [n for n in stock if n in aliases]
    if target_stock and existing:
        target_stock = existing[0]
    header_panel.replace_stock(text, after, existing, target_stock)
    text = after.read_text()
    key = io.PREFIX + route.port + "--"
    old = tokens(text)
    names = [n for n in old if not n.startswith(key)]
    if strip and route.port == "spi2":
        # Per-client caps must not enable SPI2. Ignore them only in the private
        # ownership baseline; the actual candidate keeps them for validation.
        names = [n for n in names if not n.startswith(io.PREFIX + "spi2-cs")]
    if not strip and route.provider:
        pos = next((i for i, n in enumerate(old) if n.startswith(key)), len(names))
        install_blob(folder, route.provider, io.overlay(route.port, list(route.values)))
        names.insert(pos, route.provider)
    write_selection(text, after, names)


def pins(tree):
    io.board(tree)
    claims = header_gpio.claims("a733", tree)
    labels = {(DEBUG, "PB9"): "UART0 TX · debug", (DEBUG, "PB10"): "UART0 RX · debug",
              (io.CAMERA, "PE0"): "Камера VIN · MCLK"}
    for port, (node, _, pads, _) in io.ROUTES.items():
        path = io.SOC + node
        signals = SPI_SIGNALS.get(port, ("SCL", "SDA") if port.startswith("i2c") else ("TX", "RX"))
        port_label = port.upper().replace("I2C", "I²C")
        for pad, signal in zip(pads.split(), signals, strict=True):
            labels[path, pad] = f"{port_label} {signal}"
        if port in io.UART_FLOW:
            for pad, signal in zip(io.UART_FLOW[port][0].split(), ("RTS", "CTS")):
                labels[path, pad] = f"{port_label} {signal}"
    for cs, (pad, _) in io.SPI2_CS.items():
        labels[io.SOC + io.ROUTES["spi2"][0], pad] = f"SPI2 CS{cs}"
    pwm_paths = {pwm.channel("a733", n): ("S_PWM0-2" if n == 22 else f"PWM0-{n}") for n in pwm.A733}
    for n, pad in pwm.A733.items():
        path = pwm.channel("a733", n)
        labels[path, pad] = pwm_paths[path]
    return [dict(pin=pin, pad=pad, functions=sorted({label for (path, p), label in labels.items()
                 if p == pad and path != io.CAMERA}), owners=[dict(path=path, label=labels.get((path, pad),
                 "Тестовый драйвер PIO" if path == io.PIN_TEST else pwm_paths.get(path, path)))
                 for path in sorted(claims.get(pad, ()))]) for pin, pad in PADS.items()]


def conflicts(rows):
    # The stock vendor DT reserves the debug UART pair through both nodes.
    # Keep them visible, allow this exact reservation on unrelated saves/undo.
    return header_panel.conflict_messages([r for r in rows if not (
        r["pad"] in ("PB9", "PB10") and {o["path"] for o in r["owners"]} == {DEBUG, io.PIN_TEST})])


def inventory(tree, dt=None, devices=None):
    rows, buses = [], []
    for port in SPI_SIGNALS:
        path = io.SOC + io.ROUTES[port][0]
        if not enabled(tree, path):
            continue
        buses.append(port.upper())
        for child in header_panel.clients(tree, path):
            cs, = cells(tree[child]["reg"])
            caps = cells(tree[child].get("spi-max-frequency", b""))
            hz = caps[0] if len(caps) == 1 else None
            selects = io.SPI2_CS if port == "spi2" else SPI3_CS
            pad, pin = selects.get(cs, (None, None))
            row = dict(bus=port.upper(), cs=cs, pin=pin, pad=pad, ceiling_hz=hz,
                       mode=int("spi-cpha" in tree[child]) + 2*int("spi-cpol" in tree[child]),
                       device=", ".join(strings(tree[child].get("compatible", b""))) or child.split("/")[-1])
            if dt is not None:
                node = (dt / child.lstrip("/")).resolve()
                endpoints = ["/dev/"+dev.name for dev in devices.glob(f"spidev*.{cs}")
                             if re.fullmatch(r"spidev\d+\.\d+", dev.name) and
                             (dev/"device/of_node").resolve() == node]
                row["endpoint"] = endpoints[0] if len(endpoints) == 1 else None
            rows.append(row)
    rows.sort(key=lambda row: (row["bus"], row["cs"]))
    return dict(profile="a733", buses=buses, pins=pins(tree), rows=rows)


def route_issues(route, base, before, after):
    if route.port in RESERVES:
        if not route.values and not enabled(after, route.path):
            return [f"Другой оверлей удерживает штатное устройство выключенным: {route.path}."]
        return []
    if enabled(base, route.path):
        return [f"{route.label}: маршрут уже задаёт другой оверлей ({route.path})."]
    if enabled(after, route.path) != bool(route.values):
        return [f"Итоговый DTB не подтверждает выбранный маршрут: {route.label}."]
    if route.group in ("I²C", "SPI") and not route.values and enabled(before, route.path):
        clients = header_panel.clients(before, route.path)
        if route.port == "spi3":
            clients = [c for c in clients if strings(before[c].get("compatible", b"")) != ["rohm,dh2228fv"]]
        if clients:
            return ["Маршрут обслуживает " + ", ".join(clients)]
    if route.group == "PWM" and (route.values or enabled(before, route.path)):
        n = int(route.port[3:])
        users = pwm.consumers(before, pwm.controller("a733", n)).get(n % 10, set())
        if users:
            return ["Канал PWM обслуживает " + ", ".join(sorted(users))]
    return []


def validate_stock_pwm(tree, env):
    """Validate selected stock pin routes on apply and undo, including foreign DT edits."""
    names = {n.removeprefix("sun60i-a733-") for n in io.environment(env).get("overlays", "").split()}
    for n in pwm.A733:
        if ("spwm2" if n == 22 else f"pwm{n}") not in names:
            continue
        path = pwm.channel("a733", n)
        ctrl = pwm.controller("a733", n)
        provider = tree[ctrl]
        compat = "allwinner,sunxi-pwm-v204" if n == 22 else "allwinner,sunxi-pwm-v203"
        refs = cells(provider["sunxi-pwms"])
        if (not enabled(tree, path) or not enabled(tree, ctrl) or compat not in strings(provider["compatible"])
                or len(refs) != 10 or cells(provider["pwm-base"]) != [20 if n == 22 else 0]
                or cells(tree[path]["phandle"]) != [refs[n % 10]]):
            raise ValueError(f"Неверный контроллер или отключённый PWM-канал {n}: {path}")
        pwm.a733_mux_pin(tree, n)


def compose(work):
    root = work / "boot"
    script = (root / "boot.scr").read_bytes()
    if not all(t in script for t in (b"armbianEnv.txt", b"overlay-user/${overlay_file}.dtbo")):
        raise ValueError("Unrecognized Armbian user-overlay boot route")
    for name in ("before", "after", "base.env"):
        if not (work/name).exists():
            continue
        text = (work/name).read_text()
        env = io.environment(text)
        if any(k.startswith("param_") or k in ("overlaydir", "overlay_path", "fdt_overlays") for k in env):
            raise ValueError("Unsupported boot overlay fixup or custom path")
        out = work / ("base.dtb" if name == "base.env" else name + ".dtb")
        io.compose(root, text, out, check_clocks=False)
