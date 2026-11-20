"""Read the simulated node's phone API without printing channel keys or positions."""
from contextlib import closing
from sim_client import connect_simulator

with closing(connect_simulator()) as client:
    node = client.getMyNodeInfo()
    if not node or not client.metadata or not client.metadata.firmware_version:
        raise SystemExit("No node metadata received from the simulator")
    print(f"Simulated node: {node['user']['id']}")
    print(f"Firmware: {client.metadata.firmware_version}")
