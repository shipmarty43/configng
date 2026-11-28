"""Zero 2W header routes and pin ownership for BUS002."""
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import re

import i2c_clocks
import pwm_routes as pwm
import uart_routes as uart
from header_gpio import PADS, location
import header_gpio_live as gpio
from spi1_radios import BUS, CLIENTS, CONTROL

HEADER = PADS["h618"]
NUMBERS = {pad: pin for pin, pad in HEADER.items()}
# Signal order is SCL, SDA. Only routes reaching the 40-pin connector.
I2C = {"i2c0-pi": ("PI5", "PI6"), "i2c1-pi": ("PI7", "PI8"),
       "i2c2-pi": ("PI9", "PI10"), "i2c2-ph": ("PH2", "PH3"),
       "i2c3-ph": ("PH4", "PH5"), "i2c4-ph": ("PH6", "PH7")}
SPI_CHOICES = {"single": "SX1262", "shared": "SX1262 + CC1101 + nRF24", "off": "Выключить профиль SPI1"}


@dataclass(frozen=True)
class Route:
    group: str
    port: str
    mode: str
    path: str
    pads: tuple
    signals: tuple

    @property
    def label(self):
        pins = "/".join(str(NUMBERS[p]) for p in self.pads)
        mode = {"off": "убрать маршрут", "txrx": "TX/RX", "txrx-ph": "TX/RX PH", "rtscts": "RTS/CTS",
                "rtscts-ph": "RTS/CTS PH", "rs485": "RS-485", "rs485-ph": "RS-485 PH"}.get(self.mode, self.mode.upper())
        return f"{self.port.upper()} · {mode}" + (f" · {pins}" if pins else "")


def routes():
    result = {}
    def add(group, port, mode, path, pads, signals):
        result[f"{port}-{mode}"] = Route(group, port, mode, path, tuple(pads), tuple(signals))
        result[f"{port}-off"] = Route(group, port, "off", path, (), ())
    for name, pads in I2C.items():
        port, bank = name.split("-")
        add("I²C", port, bank, i2c_clocks.BUSES["twi"+port[-1]], pads, ("SCL", "SDA"))
    for port in uart.ROUTES:
        if port == "uart0":
            continue
        for mode in ["txrx", *(m for p, m in uart.FLOW if p == port)]:
            pads = uart.route_pins(port, mode)
            handshake = ("DE" if mode.startswith("rs485") else "RTS", "CTS")
            add("UART", port, mode, uart.address(port), pads, ("TX", "RX", *handshake)[:len(pads)])
    add("UART", "uart2", "txrx-ph", uart.address("uart2"), uart.FLOW["uart2", "rtscts-ph"][0][:2], ("TX", "RX"))
    for n, pads in pwm.PINS.items():
        for pad in pads:
            add("PWM", f"pwm{n}", pad.lower(), pwm.channel_node(n), (pad,), ("PWM",))
    return result


ROUTES = routes()


def choices():
    return ([dict(group="SPI1", id=k, label=v) for k, v in SPI_CHOICES.items()] +
            [dict(group=r.group, id=k, label=r.label) for k, r in sorted(ROUTES.items())])


def edit(route, before, after, folder):
    """Only replace the selected controller's own recognized route."""
    if route.group == "UART":
        if route.mode == "txrx-ph":
            text = before.read_text()
            routes = [name for name in pwm.stock(text) if name.startswith("uart2-")]
            if routes == ["uart2-ph"] and uart.selected_mode("uart2", uart.tokens(text)) is None:
                after.write_bytes(before.read_bytes())
                return
            # This stock route has the correct UART2 function on PH5/PH6.
            uart.prepare(before, after, folder, route.port, "disable")
            replace_stock(after.read_text(), after, [], "uart2-ph")
            return
        action = {"off": "disable", "txrx": "enable"}.get(route.mode, "enable-" + route.mode)
        uart.prepare(before, after, folder, route.port, action)
        return
    text = before.read_text()
    if route.group == "PWM":
        after.write_text(pwm.edit(text, int(route.port[-1]), None if route.mode == "off" else route.pads[0]))
        return
    stock = pwm.stock(text)
    occupied = [n for n in stock if n.startswith(route.port + "-")]
    if any(n not in I2C for n in occupied):
        raise ValueError(f"{route.port.upper()} использует маршрут вне гребёнки: {' '.join(occupied)}")
    replace_stock(text, after, occupied, None if route.mode == "off" else f"{route.port}-{route.mode}")


def replace_stock(text, after, occupied, target):
    stock = pwm.stock(text)
    new = [n for n in stock if n not in occupied]
    if target:
        new.insert(stock.index(occupied[0]) if occupied else len(new), target)
    if new != stock:
        line = "overlays=" + " ".join(new)
        text = (re.sub(r"^overlays=.*$", line, text, flags=re.M) if re.search("^overlays=", text, re.M)
                else text + ("" if text.endswith("\n") else "\n") + line + "\n")
    after.write_text(text)


def default_pins(tree, path):
    handles = {p["phandle"]: p for loc, p in tree.items()
               if loc.rpartition("/")[0] == uart.PIO and "phandle" in p}
    props = tree[path]
    return [(pin, function) for ref in uart.cells(props.get("pinctrl-0", b""))
            for group in [handles.get(ref.to_bytes(4, "big"), {})]
            for function in uart.strings(group.get("function", b""))
            for pin in uart.strings(group.get("pins", b""))]


def clients(tree, path):
    return [p for p in tree if p.rpartition("/")[0] == path and
            "reg" in tree[p] and tree[p].get("status", b"okay\0") in (b"okay\0", b"ok\0")]


def route_issues(route, base, before, after):
    path = route.path
    if route.group == "PWM":
        foreign = pwm.routed_pin(base, int(route.port[-1])) is not None
    else:
        foreign = uart.enabled(base, path)
    if foreign:
        return [f"{route.port.upper()} уже настроен другим владельцем в Device Tree ({path})."]
    if route.group == "I²C" and uart.enabled(before, path) and (not route.pads or
            default_pins(before, path) != default_pins(after, path)):
        devices = clients(before, path)
        if devices:
            return [f"{route.port.upper()} обслуживает {', '.join(p.rsplit('/',1)[1] for p in devices)}. "
                    "Сначала освободите устройства на этом маршруте."]
    if route.pads:
        pins = default_pins(after, path)
        if not uart.enabled(after, path) or pins != [(pad, route.port) for pad in route.pads]:
            return [f"Итоговый DTB не назначает {route.label} контроллеру {path}."]
    return []


def signals(tree):
    labels = {}
    def put(path, pad, label):
        labels[path, pad] = label
    ups = i2c_clocks.BUSES["twi1"] + "/ups@10"
    ups_active = (ups in tree and uart.enabled(tree, ups) and
                  "dfrobot,dfr0528" in uart.strings(tree[ups].get("compatible", b"")))
    for route in ROUTES.values():
        for pad, signal in zip(route.pads, route.signals):
            if signal in ("DE", "RTS"):
                signal = "DE" if uart.DE_PROP in tree.get(route.path, {}) else "RTS"
            port = route.port.upper().replace("I2C", "I²C")
            name = f"{port} {signal}" if signal != "PWM" else port
            if route.port == "i2c1" and ups_active:
                name += " · DFR0528"
            put(route.path, pad, name)
    for pad, signal in zip(uart.ROUTES["uart0"][:2], ("TX", "RX")):
        put(uart.address("uart0"), pad, "UART0 " + signal)
    for pad, signal in (("PH6", "CLK"), ("PH7", "MOSI"), ("PH8", "MISO")):
        put(BUS, pad, "SPI1 " + signal)
    pio = tree.get(uart.PIO, {}).get("phandle")
    cs = uart.cells(tree.get(BUS, {}).get("cs-gpios", b""))
    for idx in range(0, len(cs), 4):
        spec = cs[idx:idx+4]
        if len(spec) == 4 and spec[0].to_bytes(4, "big") == pio and spec[1] < 26:
            put(BUS, f"P{chr(65+spec[1])}{spec[2]}", f"SPI1 CS{idx//4}")
    return labels


def pins(tree):
    if uart.PIO not in tree:
        return []
    claims = uart.owners(tree)
    labels = signals(tree)
    phandle = tree[uart.PIO].get("phandle")
    bus = tree.get(BUS, {})
    waveshare_single = (phandle is not None and uart.cells(bus.get("num-cs", b"")) == [1] and
                        uart.cells(bus.get("cs-gpios", b"")) == [int.from_bytes(phandle, "big"), 8, 3, 1] and
                        set(default_pins(tree, BUS)) == {("PH6", "spi1"), ("PH7", "spi1"), ("PH8", "spi1")})

    # The single-HAT overlay describes NSS but the directly mounted Waveshare
    # also wires four sidebands. They remain occupied in that profile.
    for cs, mapping in CONTROL.items():
        node, compatible, _ = CLIENTS[cs]
        path = f"{BUS}/{node}"
        if path not in tree or not uart.enabled(tree, path) or compatible not in uart.strings(tree[path].get("compatible", b"")):
            continue
        for prop, (bank, bit, _) in mapping.items():
            spec = uart.cells(tree[path].get(prop, b""))
            if len(spec) == 4 and spec[0].to_bytes(4, "big") == phandle and spec[1] < 26:
                pad = f"P{chr(65+spec[1])}{spec[2]}"
            elif prop not in tree[path] and cs == 0 and waveshare_single:
                pad = f"P{chr(65+bank)}{bit}"
                claims.setdefault(pad, set()).add(path)
            else:
                continue
            labels[path, pad] = ("SX1262" if cs == 0 else "nRF24") + " " + prop.split("-")[0].upper()
    return [dict(pin=pin, pad=pad, owners=[
        dict(path=path, label=labels.get((path, pad), path)) for path in sorted(claims.get(pad, ()))])
        for pin, pad in HEADER.items()]


def gpio_consumers(rows, dt, sysroot=Path("/sys"), devroot=Path("/dev"), *, board="h618"):
    """GPIO v2 line info only. An offline DT or inaccessible gpiochip stays unknown."""
    if (sysroot / "firmware/devicetree/base").resolve() != dt.resolve():
        return False
    try:
        with ExitStack() as stack:
            chips = gpio.discover(board, stack, sysroot, devroot)
            for row in rows:
                _, ctl, bank, bit = location(board, row["pin"])
                if ctl not in chips:
                    return False
                flags, owner, _ = chips[ctl].info(bank * 32 + bit)
                if flags & gpio.USED:
                    row["gpio_consumer"] = owner or "занято ядром"
            return bool(rows)
    except (OSError, ValueError):
        return False


def changes(before, after):
    old = {r["pin"]: r["owners"] for r in before}
    return [dict(pin=r["pin"], pad=r["pad"], before=old.get(r["pin"], []), after=r["owners"])
            for r in after if r["owners"] != old.get(r["pin"], [])]


def conflict_messages(rows):
    return [f"Вывод {r['pin']} ({r['pad']}): " + " ↔ ".join(o["label"] for o in r["owners"])
            for r in rows if len(r["owners"]) > 1]
