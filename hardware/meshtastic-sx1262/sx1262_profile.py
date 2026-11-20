"""Generate and preflight the Zero 2W Portduino profile without probing the radio."""
import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import struct
from string import Template
import sys
import time
from contextlib import closing

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "zero2w-waveshare.yaml.in"
BINARY = Path("/opt/opi-mesh/meshtasticd")
DIGEST = "2b37b97948ebd9a75f22d52f653ce4977b6b6be9afdb7c5c02a973bd34e15653"
STATE = Path("/var/lib/opi-meshtastic-radio")
RUNTIME = Path("/run/opi-meshtastic-radio")
VFS = STATE / "firmware"
ACCESS = Path("/etc/systemd/system/opi-meshtastic-radio.service.d/50-devices.conf")
PROFILE = Path("/etc/armbian-config/sx1262-profile")
LOCK = Path("/run/lock/opi-radio.lock")


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
    require("semtech,sx1262" in names(radio/"compatible") and (radio/"reg").read_bytes() == cells(0)
            and (radio/"spi-max-frequency").read_bytes() == cells(2000000), "Wrong SPI endpoint or speed")
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
    return Route(spi.name, index, devno(spi), devno(chip))


def mac_address():
    machine = Path("/etc/machine-id").read_text().strip()
    require(re.fullmatch(r"[0-9a-f]{32}", machine), "Missing machine identity")
    digest = hashlib.sha256(("opi-sx1262-meshtastic:" + machine).encode()).digest()
    return ":".join(f"{n:02x}" for n in b"\x02" + digest[:5])


def render(route):
    import yaml
    mac = mac_address()
    text = Template(TEMPLATE.read_text()).substitute(spi=route.spi, chip=route.chip, mac=mac)
    expected = dict(Module="sx1262", spidev=route.spi, spiSpeed=2000000,
                    DIO2_AS_RF_SWITCH=True, DIO3_TCXO_VOLTAGE=0)
    for signal, pin, offset in (("IRQ", 36, 76), ("Busy", 38, 260), ("Reset", 12, 257), ("RXen", 31, 271)):
        expected[signal] = dict(pin=pin, gpiochip=route.chip, line=offset)
    canonical = {"Lora": expected, "General": {"MACAddress": mac, "ConfigDirectory": "", "AvailableDirectory": ""}}
    require(yaml.safe_load(text) == canonical, "Hardware YAML differs from the qualified Zero 2W route")
    # Emit a single unambiguous mapping for yaml-cpp (including scalar types).
    return yaml.safe_dump(canonical, sort_keys=False)


def verify_binary():
    with BINARY.open("rb") as stream:
        require(hashlib.file_digest(stream, "sha256").hexdigest() == DIGEST,
                "Unqualified meshtasticd binary (expected tested ARM64 build 2.7.26)")


def preferences(vfs=VFS):
    from meshtastic.protobuf import config_pb2, localonly_pb2
    from google.protobuf.message import DecodeError
    try:
        cfg = localonly_pb2.LocalConfig.FromString((vfs/"prefs/config.proto").read_bytes())
    except DecodeError as err:
        raise ValueError("Damaged firmware preferences") from err
    require(cfg.version == 24 and cfg.HasField("device") and cfg.HasField("lora")
            and cfg.device.role == config_pb2.Config.DeviceConfig.CLIENT_MUTE
            and cfg.lora.region == config_pb2.Config.LoRaConfig.EU_433 and not cfg.lora.tx_enabled
            and cfg.lora.use_preset and cfg.lora.modem_preset == config_pb2.Config.LoRaConfig.LONG_FAST
            and not cfg.lora.channel_num and not cfg.lora.override_frequency and not cfg.lora.frequency_offset
            and not cfg.lora.override_duty_cycle, "Expected v24 CLIENT_MUTE, EU_433, TX disabled, no frequency overrides")
    require(not (vfs/"prefs/db.proto").exists(), "Legacy preferences can trigger a firmware reset")


def device_policy(route):
    return ("[Service]\n" +
            "".join(f"BindPaths=/dev/{name}\nDeviceAllow=/dev/{name} rw\n"
                    for name in (route.spi, f"gpiochip{route.chip}")))


def gate(route):
    require(PROFILE.exists() and PROFILE.read_text().strip() == "hardware", "Hardware profile is not selected")
    require(ACCESS.is_file() and ACCESS.read_text() == device_policy(route),
            "Hardware access is sealed: no qualified device binding for this route")


def check():
    route = discover()
    render(route)
    verify_binary()
    preferences(VFS)
    return route


def check_bindings(route, dev=Path("/dev")):
    for name, number in ((route.spi, route.spi_dev), (f"gpiochip{route.chip}", route.chip_dev)):
        node = (dev/name).stat()
        require(stat.S_ISCHR(node.st_mode) and f"{os.major(node.st_rdev)}:{os.minor(node.st_rdev)}" == number,
                f"Incorrect device binding: {name}")


def launch():
    route = check()
    gate(route)
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Invalid radio lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Revalidate inside the service mount namespace while holding the owner lock.
        require(check() == route, "Radio route changed during handoff")
        gate(route)
        check_bindings(route)
        config = RUNTIME / "config.yaml"
        config.write_text(render(route))
        os.set_inheritable(fd, True)
        os.execv(BINARY, [str(BINARY), "--config", str(config), "--fsdir", str(VFS)])
    finally:
        os.close(fd)


def ready(port=4403):
    from meshtastic.protobuf import config_pb2
    from sim_client import connect_simulator  # Pinned SDK, loopback phone API only.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            client = connect_simulator(port, 6)
        except ConnectionRefusedError:
            time.sleep(0.2)
            continue
        with closing(client):
            cfg = client.localNode.localConfig
            number = int(mac_address().replace(":", "")[-8:], 16)
            require(client.myInfo.my_node_num == number and client.metadata.firmware_version == "2.7.26"
                    and cfg.device.role == config_pb2.Config.DeviceConfig.CLIENT_MUTE
                    and cfg.lora.region == config_pb2.Config.LoRaConfig.EU_433 and not cfg.lora.tx_enabled
                    and cfg.lora.use_preset and cfg.lora.modem_preset == config_pb2.Config.LoRaConfig.LONG_FAST
                    and not cfg.lora.frequency_offset and not cfg.lora.override_frequency and not cfg.lora.channel_num
                    and not cfg.lora.override_duty_cycle, "Unexpected live firmware settings or identity")
            return
    raise TimeoutError("Hardware backend did not complete initialization")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("check", "render", "device-policy", "preflight", "start", "ready"))
    args = cli.parse_args()
    if args.command == "start":
        launch()
        return
    if args.command == "ready":
        gate(check())
        ready()
        return
    route = discover() if args.command in ("render", "device-policy") else check()
    if args.command == "render":
        print(render(route), end="")
    elif args.command == "device-policy":
        print(device_policy(route), end="")
    else:
        if args.command == "preflight":
            gate(route)
        print(f"Waveshare SX1262: {route.spi}, kernel CS0/PI3, 2 MHz; gpiochip{route.chip}")
        print("DIO1 PC12/76, BUSY PI4/260, RESET PI1/257, RXen PI15/271; DIO2 switch, crystal")
        print("Firmware 2.7.26: EU_433, CLIENT_MUTE, tx_enabled=false")
        print("Device binding:", "present" if ACCESS.is_file() and ACCESS.read_text()==device_policy(route) else "sealed")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
