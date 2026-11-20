"""Prepare radio preferences and check the native parser in a device-free unit."""
import argparse
from contextlib import closing, contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time

import yaml
from meshtastic.protobuf import config_pb2, localonly_pb2
from sim_client import connect_simulator
import sx1262_profile as profile

PORT = 14703


def isolated():
    names = {n for _, n in socket.if_nameindex()}
    forbidden = ("spidev*", "gpiochip*", "i2c-*", "ttyS*", "ttyUSB*", "bus/usb")
    profile.require(names == {"lo"} and not any(any(Path("/dev").glob(p)) for p in forbidden)
                    and not Path("/dev/mem").exists(), "Run inside PrivateNetwork=yes and PrivateDevices=yes")


@contextmanager
def simulator(directory):
    isolated()
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen([str(profile.BINARY), "--sim", "--hwid", "16898711",
                                 "--fsdir", str(directory), "--port", str(PORT)],
                                cwd=directory, stdout=log, stderr=subprocess.STDOUT)
        try:
            end = time.monotonic() + 20
            while time.monotonic() < end and proc.poll() is None:
                try:
                    client = connect_simulator(PORT, 7)
                except ConnectionRefusedError:
                    time.sleep(0.2)
                    continue
                with closing(client):
                    yield client
                return
            raise RuntimeError("Isolated simulator failed to initialize")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def seed(state):
    target = state / "firmware"
    with (state/".prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if target.exists():
            profile.preferences(target)
            print("Existing firmware preferences validated and preserved.")
            return
        with tempfile.TemporaryDirectory(dir=state) as temporary:
            root = Path(temporary)
            source = root / "defaults"
            with simulator(source) as client:
                # Force the pinned firmware to persist its own versioned defaults.
                # Region selection happens offline, never during hardware startup.
                client.localNode.localConfig.lora.tx_enabled = False
                client.localNode.writeConfig("lora")
                file = source/"prefs/config.proto"
                end = time.monotonic() + 8
                while not file.exists() and time.monotonic() < end:
                    time.sleep(0.1)
            cfg = localonly_pb2.LocalConfig.FromString(file.read_bytes())
            profile.require(cfg.version == 24 and cfg.HasField("device") and cfg.HasField("lora"),
                            "Unexpected firmware defaults")
            cfg.ClearField("security")  # Never promote simulator key material.
            cfg.device.role = config_pb2.Config.DeviceConfig.CLIENT_MUTE
            cfg.lora.region = config_pb2.Config.LoRaConfig.EU_433
            cfg.lora.use_preset = True
            cfg.lora.modem_preset = config_pb2.Config.LoRaConfig.LONG_FAST
            cfg.lora.tx_enabled = False
            cfg.lora.override_frequency = cfg.lora.frequency_offset = 0
            cfg.lora.channel_num = 0
            cfg.lora.override_duty_cycle = False
            staged = root/"staged"
            (staged/"prefs").mkdir(parents=True, mode=0o700)
            with (staged/"prefs/config.proto").open("xb") as out:
                out.write(cfg.SerializeToString())
                out.flush()
                os.fsync(out.fileno())
            profile.preferences(staged)
            # Reopen a COPY in the unmodified native firmware. Keep any generated
            # keys or NodeDB from this validation out of the hardware state.
            check = root/"readback"
            shutil.copytree(staged, check)
            with simulator(check) as client:
                actual = client.localNode.localConfig
                profile.require(actual.device.role == cfg.device.role and actual.lora.region == cfg.lora.region
                                and actual.lora.use_preset and actual.lora.modem_preset == cfg.lora.modem_preset
                                and not actual.lora.tx_enabled, "Phone API preference readback mismatch")
            os.rename(staged, target)
            print("Native readback: CLIENT_MUTE, EU_433, LONG_FAST, tx_enabled=false. Fresh seed installed.")


def native_check():
    route = profile.check()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root/"config.yaml"
        source.write_text(profile.render(route))
        result = subprocess.run([str(profile.BINARY), "--output-yaml", "--config", str(source),
                                 "--fsdir", temporary], text=True, capture_output=True, timeout=12, cwd=root)
        profile.require(result.returncode == 0 and "Lora:" in result.stdout, "Native output-yaml failed")
        parsed = yaml.safe_load("Lora:" + result.stdout.split("Lora:", 1)[1])
        lora = parsed["Lora"]
        expected = yaml.safe_load(source.read_text())["Lora"].copy()
        # The upstream emitter omits defaults for speed and crystal selection.
        lora.setdefault("spiSpeed", 2000000)
        lora.setdefault("DIO3_TCXO_VOLTAGE", 0)
        profile.require(lora == expected, f"Native LoRa parser differs: {lora}")
        profile.require(parsed["General"].get("MACAddress", "").replace(":", "").lower() == profile.mac_address().replace(":", "")
                        and not parsed["General"].get("ConfigDirectory"), "Unexpected native general settings")
        print("Native ARM64 YAML round trip passed: SPI endpoint, four translated pins, crystal and DIO2.")
        scratch = root/"negative"
        scratch.mkdir()
        result = subprocess.run([str(profile.BINARY), "--config", str(source), "--fsdir", str(scratch)],
                                capture_output=True, text=True, timeout=15, cwd=root)
        output = result.stdout + result.stderr
        profile.require(result.returncode != 0 and f"Initializing GPIO36 on chip gpiochip{route.chip}" in output
                        and ("Error setting pin number" in output or "LinuxGPIOPin::getLine" in output),
                        f"Expected failure on unavailable GPIO, got exit {result.returncode}")
        print("Real hardware initialization path stopped at the first unavailable GPIO in private /dev.")


if __name__ == "__main__":
    os.umask(0o077)
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("seed", "native-check"))
    action = cli.parse_args().action
    isolated()
    profile.verify_binary()
    if action == "seed":
        seed(profile.STATE)
    else:
        native_check()
