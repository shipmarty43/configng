"""Provision the dedicated virtual firmware's region through its local phone API."""
from contextlib import closing
from pathlib import Path
import socket
import subprocess
import tempfile
import time

from google.protobuf.json_format import ParseDict
from meshtastic.protobuf import config_pb2, localonly_pb2, mesh_pb2, portnums_pb2
from sim_client import connect_simulator


def require_sim_namespace():
    if ({n for _, n in socket.if_nameindex()} != {"lo"} or any(Path("/dev").glob("gpiochip*"))
            or any(Path("/dev").glob("spidev*"))):
        raise RuntimeError("Expected the dedicated simulator namespace")


def configure_region(client):
    lora = client.localNode.localConfig.lora
    if lora.region != config_pb2.Config.LoRaConfig.UNSET:
        return
    lora.region = config_pb2.Config.LoRaConfig.EU_433
    client.localNode.writeConfig("lora")


def advertise(client):
    user = ParseDict(client.getMyNodeInfo()["user"], mesh_pb2.User(), ignore_unknown_fields=True)
    if len(user.public_key) != 32:
        raise ValueError("Simulator has not published its DM key")
    client.sendData(user, portNum=portnums_pb2.PortNum.NODEINFO_APP, wantResponse=True)


def prepare(directory, config, port):
    require_sim_namespace()
    prefs = directory / "prefs/config.proto"

    def configured():
        return prefs.exists() and localonly_pb2.LocalConfig.FromString(
            prefs.read_bytes()).lora.region != config_pb2.Config.LoRaConfig.UNSET

    if configured():
        return
    # Use the firmware API to create preferences. The normal, subsequent startup
    # derives the owner NodeInfo from the saved region and its own key pair.
    with tempfile.TemporaryFile() as log:
        args = ["/opt/opi-mesh/meshtasticd", "--config", str(config),
                "--port", str(port), "--fsdir", str(directory)]
        process = subprocess.Popen(args, cwd=directory, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 25
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    client = connect_simulator(port, 8)
                except ConnectionRefusedError:
                    time.sleep(0.25)
                    continue
                with closing(client):
                    configure_region(client)
                    while time.monotonic() < deadline:
                        if configured():
                            return
                        time.sleep(0.25)
                break
            raise RuntimeError("Simulator failed to persist its region")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    prepare(Path("/var/lib/opi-meshtastic-sim"), Path("/opt/opi-mesh/meshtastic-sim.yaml"), 4403)
