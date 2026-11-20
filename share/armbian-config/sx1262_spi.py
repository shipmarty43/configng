"""SPI clock policy for the H618 header SX1262. Saving never opens spidev."""
import os
from pathlib import Path
import re
import tempfile

SETTING = Path("/etc/armbian-config/sx1262-spi-hz")
DT = Path("/sys/firmware/devicetree/base/soc/spi@5011000/radio@0/spi-max-frequency")
MAX_HZ = 2_000_000


def ceiling(prop=DT):
    data = prop.read_bytes()
    if len(data) != 4 or int.from_bytes(data, "big") == 0:
        raise ValueError("Invalid spi-max-frequency in the SX1262 device tree")
    return min(MAX_HZ, int.from_bytes(data, "big"))


def parse(value, limit):
    if not re.fullmatch(r"[0-9]{1,7}", value) or not 1 <= int(value) <= limit:
        raise ValueError(f"SPI clock must be an integer in 1..{limit} Hz")
    return int(value)


def selected(limit, path=None):
    path = SETTING if path is None else path
    try:
        return parse(path.read_text().removesuffix("\n"), limit)
    except FileNotFoundError:
        return limit


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
