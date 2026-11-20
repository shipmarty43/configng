"""Read the simulated node's phone API without printing channel keys or positions."""
from contextlib import closing
from threading import Event
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub

connected = Event()


def established(interface):
    connected.set()


pub.subscribe(established, "meshtastic.connection.established")
with closing(TCPInterface(hostname="127.0.0.1", portNumber=4403, timeout=12)) as client:
    if not connected.wait(5):
        raise SystemExit("Simulator handshake timed out")
    node = client.getMyNodeInfo()
    if not node or not client.metadata or not client.metadata.firmware_version:
        raise SystemExit("No node metadata received from the simulator")
    print(f"Simulated node: {node['user']['id']}")
    print(f"Firmware: {client.metadata.firmware_version}")
