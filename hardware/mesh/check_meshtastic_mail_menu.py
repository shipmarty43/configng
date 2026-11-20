"""Second simulated firmware node for the installed configurator's UI test."""
import argparse
from contextlib import ExitStack
from pathlib import Path
from queue import Empty, Queue
import socket
import time

from pubsub import pub

from check_meshtastic_sim import start_node
from sim_region import advertise

PRIMARY = 0x01010101
PEER = 0x22334402


def check(root, label):
    if {name for _, name in socket.if_nameindex()} != {"lo"} or Path("/dev/gpiochip0").exists():
        raise RuntimeError("Expected the simulator's loopback-only namespace and private devices")
    with ExitStack() as stack:
        peer = start_node(stack, root, 1, prepare_region=True)
        if peer.myInfo.my_node_num != PEER:
            raise RuntimeError("Unexpected second simulator ID")
        replies = Queue()

        def incoming(packet, interface):
            if interface is peer and packet.get("from") == PRIMARY and packet.get("to") == PEER:
                replies.put(packet)

        pub.subscribe(incoming, "meshtastic.receive.text")
        stack.callback(pub.unsubscribe, incoming, "meshtastic.receive.text")
        # Advertise the peer using its own firmware-provided name and public key.
        advertise(peer)
        print("Peer is ready; choose Discover nodes on the primary simulator", flush=True)
        deadline = time.monotonic() + 115
        while not peer.nodesByNum.get(PRIMARY, {}).get("user", {}).get("publicKey"):
            if time.monotonic() >= deadline:
                raise TimeoutError("Primary simulator has not announced its DM key")
            time.sleep(0.5)
        question = f"Привет от узла B [{label}]"
        answer = f"Ответ из меню A [{label}]"
        packet = peer.sendText(question, destinationId=PRIMARY, wantAck=True)
        print(f"B -> A packet {packet.id}; waiting for exact A -> B direct text", flush=True)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            try:
                reply = replies.get(timeout=max(0, deadline-time.monotonic()))
            except Empty:
                break
            if reply.get("decoded", {}).get("text") == answer:
                print(f"PASS: directed reply packet {reply['id']} from !{PRIMARY:08x} to !{PEER:08x}", flush=True)
                # Keep the peer alive long enough to send its routing acknowledgement.
                time.sleep(3)
                return
        raise TimeoutError("No matching directed reply")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("state", type=Path)
    cli.add_argument("label")
    args = cli.parse_args()
    check(args.state, args.label)
