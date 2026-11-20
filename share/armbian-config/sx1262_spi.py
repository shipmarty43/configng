"""Read-only H618 header routing and next-start SPI clock policy."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import struct
import tempfile

SETTING = Path("/etc/armbian-config/sx1262-spi-hz")
DT = Path("/sys/firmware/devicetree/base/soc/spi@5011000/radio@0/spi-max-frequency")
MIN_HZ = 3_000
DEFAULT_HZ = 2_000_000
MAX_HZ = 16_000_000  # Semtech DS.SX1261-2, table 8-1: tSCK >= 62.5 ns


def ceiling(prop=DT):
    data = prop.read_bytes()
    if len(data) != 4 or int.from_bytes(data, "big") < MIN_HZ:
        raise ValueError("Invalid spi-max-frequency in the SX1262 device tree")
    return min(MAX_HZ, int.from_bytes(data, "big"))


def parse(value, limit):
    if not re.fullmatch(r"[0-9]{1,8}", value) or not MIN_HZ <= int(value) <= min(limit, MAX_HZ):
        raise ValueError(f"SPI clock must be an integer in {MIN_HZ}..{min(limit, MAX_HZ)} Hz")
    return int(value)


def selected(limit, path=None):
    path = SETTING if path is None else path
    try:
        return parse(path.read_bytes().decode("ascii").removesuffix("\n"), limit)
    except FileNotFoundError:
        return min(DEFAULT_HZ, limit)


def save(value, limit, path=SETTING):
    speed = None if value == "default" else parse(value, limit)
    path.parent.mkdir(parents=True, exist_ok=True)
    if speed is None:
        path.unlink(missing_ok=True)
    else:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as out:
            try:
                out.write(f"{speed}\n")
                os.fchmod(out.fileno(), 0o644)
                out.flush()
                os.fsync(out.fileno())
                os.replace(out.name, path)
            finally:
                Path(out.name).unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def cells(*values):
    return struct.pack(f">{len(values)}I", *values)


def names(path):
    data = path.read_bytes()
    require(data.endswith(b"\0"), f"Malformed DT string: {path.name}")
    return data[:-1].decode().split("\0")


def enabled(node):
    prop = node / "status"
    return not prop.exists() or names(prop) in (["okay"], ["ok"])


def only(items, label):
    items = list(items)
    require(len(items) == 1, f"Expected one {label}, found {len(items)}")
    return items[0]


@dataclass(frozen=True)
class Route:
    spi: str
    chip: int
    spi_dev: str
    chip_dev: str
    max_hz: int = DEFAULT_HZ


def devno(node):
    value = (node / "dev").read_text().strip()
    require(re.fullmatch(r"[0-9]+:[0-9]+", value), "Malformed sysfs device number")
    return value


def discover(sysroot=Path("/sys")):
    dt = sysroot / "firmware/devicetree/base"
    compat = names(dt / "compatible")
    require("xunlong,orangepi-zero2w" in compat and "allwinner,sun50i-h618" in compat, "Expected H618 Zero 2W")
    ctrl = dt / "soc/spi@5011000"
    pio = dt / "soc/pinctrl@300b000"
    group = pio / "spi1-pins"
    radio = ctrl / "radio@0"
    require(all(enabled(n) for n in (ctrl, pio, radio)), "Disabled SPI, GPIO or radio node")
    require("allwinner,sun50i-h616-pinctrl" in names(pio/"compatible")
            and not (pio/"gpio-line-names").exists(), "Unqualified GPIO layout")
    max_hz = ceiling(radio/"spi-max-frequency")
    require("semtech,sx1262" in names(radio/"compatible") and (radio/"reg").read_bytes() == cells(0), "Wrong SPI endpoint or speed")
    require(not any((radio/p).exists() for p in ("spi-cs-high","spi-cpha","spi-cpol","spi-3wire","spi-lsb-first")),
            "Expected active-low four-wire SPI mode 0, MSB first")
    gpio_handle = (pio/"phandle").read_bytes()
    group_handle = (group/"phandle").read_bytes()
    require(len(gpio_handle) == len(group_handle) == 4 and (ctrl/"num-cs").read_bytes() == cells(1)
            and (ctrl/"cs-gpios").read_bytes() == gpio_handle + cells(8,3,1), "Expected kernel CS0 on PI3")
    require((ctrl/"pinctrl-0").read_bytes() == group_handle and names(group/"function") == ["spi1"]
            and sorted(names(group/"pins")) == ["PH6","PH7","PH8"], "Unexpected SPI1 pinmux")
    require(not any(n != radio and (n/"reg").is_file() and enabled(n) and (n/"reg").read_bytes() == cells(0)
                    for n in ctrl.iterdir()), "Duplicate SPI CS0")
    spi = only((s for s in (sysroot/"class/spidev").glob("spidev*")
                if re.fullmatch(r"spidev[0-9]+\.0", s.name)
                and (s/"device/of_node").resolve() == radio.resolve()), "bound radio spidev")
    chip = only((g for g in (sysroot/"bus/gpio/devices").glob("gpiochip*")
                 if re.fullmatch(r"gpiochip[0-9]+", g.name) and (g/"of_node").resolve() == pio.resolve()), "main PIO gpiochip")
    index = int(chip.name[8:])
    gpio_class = sysroot / f"class/gpio/chip{index}"
    require((gpio_class/"label").read_text().strip() in ("300b000.pinctrl", "0300b000.pinctrl")
            and (gpio_class/"ngpio").read_text().strip() == "288", "Unknown main PIO line layout")
    return Route(spi.name, index, devno(spi), devno(chip), max_hz)



def device_policy(route):
    return ("[Service]\n" +
            "".join(f"BindPaths=/dev/{name}\nDeviceAllow=/dev/{name} rw\n"
                    for name in (route.spi, f"gpiochip{route.chip}")))
