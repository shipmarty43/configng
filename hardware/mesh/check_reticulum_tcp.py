"""Check a local rnsd using an independent TCP peer and a delivery proof."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time

import RNS

SERVER = "/var/lib/opi-reticulum"
APP = "opimeshtest"
ASPECT = "delivery"


def wait_for(predicate, seconds):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("Reticulum peer timed out")
        time.sleep(0.1)


def peer(destination_hash, payload):
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "config").write_text(
            "[reticulum]\n  share_instance = no\n  enable_transport = no\n"
            "[interfaces]\n  [[Test TCP client]]\n    type = TCPClientInterface\n"
            "    enabled = yes\n    target_host = 127.0.0.1\n    target_port = 4242\n"
        )
        RNS.Reticulum(configdir=directory)
        RNS.Transport.request_path(destination_hash)
        # RNS 1.6 generates a proof-of-work stamp for a new destination.
        wait_for(lambda: RNS.Transport.has_path(destination_hash), 560)
        identity = RNS.Identity.recall(destination_hash)
        dest = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, APP, ASPECT)
        receipt = RNS.Packet(dest, payload).send()
        wait_for(lambda: receipt.get_status() == RNS.PacketReceipt.DELIVERED, 15)


def check():
    # An installed rnsd owns the TCP server. Refuse to create a replacement.
    RNS.Reticulum(configdir=SERVER, require_shared_instance=True)
    dest = RNS.Destination(RNS.Identity(), RNS.Destination.IN, RNS.Destination.SINGLE, APP, ASPECT)
    payload = secrets.token_bytes(24)
    received = threading.Event()

    def on_packet(data, packet):
        if data == payload:
            received.set()

    dest.set_packet_callback(on_packet)
    dest.set_proof_strategy(RNS.Destination.PROVE_ALL)
    child = subprocess.Popen([sys.executable, os.path.abspath(__file__), dest.hash.hex(), payload.hex()])
    try:
        dest.announce()
        if child.wait(timeout=590) or not received.wait(2):
            raise RuntimeError("Missing application payload or delivery proof")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    print("PASS: independent TCP peer, 24 payload bytes matched, delivery proof received")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        peer(bytes.fromhex(sys.argv[1]), bytes.fromhex(sys.argv[2]))
    else:
        check()
