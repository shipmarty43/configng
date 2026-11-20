"""Generate and preflight the Zero 2W Portduino profile without probing the radio."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
from string import Template
import sys
import time
import sx1262_spi
from sx1262_spi import Route, cells, device_policy, discover, require
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


def mac_address():
    machine = Path("/etc/machine-id").read_text().strip()
    require(re.fullmatch(r"[0-9a-f]{32}", machine), "Missing machine identity")
    digest = hashlib.sha256(("opi-sx1262-meshtastic:" + machine).encode()).digest()
    return ":".join(f"{n:02x}" for n in b"\x02" + digest[:5])


def render(route):
    import yaml
    speed = sx1262_spi.selected(route.max_hz)
    mac = mac_address()
    text = Template(TEMPLATE.read_text()).substitute(spi=route.spi, chip=route.chip, mac=mac, hz=speed)
    expected = dict(Module="sx1262", spidev=route.spi, spiSpeed=speed,
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
        print(f"Waveshare SX1262: {route.spi}, kernel CS0/PI3, SPI mode 0, {sx1262_spi.selected(route.max_hz)} Hz; gpiochip{route.chip}")
        print("DIO1 PC12/76, BUSY PI4/260, RESET PI1/257, RXen PI15/271; DIO2 switch, crystal")
        print("Firmware 2.7.26: EU_433, CLIENT_MUTE, tx_enabled=false")
        print("Device binding:", "present" if ACCESS.is_file() and ACCESS.read_text()==device_policy(route) else "sealed")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
