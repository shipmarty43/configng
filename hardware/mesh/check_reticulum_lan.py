"""Two-host Reticulum acceptance check. Each host runs one role."""
import argparse
from ipaddress import IPv4Address
from pathlib import Path
import secrets
import tempfile
import threading
import time

import RNS

APP = "opimeshtest"
ASPECT = "lan"
SIZES = (32, 768)


def workstation(board):
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "config").write_text(
            "[reticulum]\n  share_instance = no\n  enable_transport = no\n"
            "[stamps]\n  max_workers = 2\n"
            "[interfaces]\n  [[Board LAN]]\n    type = TCPClientInterface\n"
            f"    enabled = yes\n    target_host = {board}\n    target_port = 4242\n"
        )
        RNS.Reticulum(configdir=directory)
        destination = RNS.Destination(RNS.Identity(), RNS.Destination.IN,
                                      RNS.Destination.SINGLE, APP, ASPECT)
        completed = threading.Event()
        sizes_by_link = {}

        def echo(path, data, request_id, link_id, remote_identity, requested_at):
            if isinstance(data, bytes) and len(data) in SIZES:
                sizes_by_link.setdefault(link_id, set()).add(len(data))
                return data

        def closed(link):
            if sizes_by_link.pop(link.link_id, set()) == set(SIZES):
                completed.set()

        destination.set_link_established_callback(lambda link: link.set_link_closed_callback(closed))
        destination.register_request_handler("/echo", echo, allow=RNS.Destination.ALLOW_ALL)
        print(f"Destination {destination.hash.hex()}", flush=True)
        destination.announce()
        if not completed.wait(540):
            raise TimeoutError("Timed out waiting for both requests and link closure")
        print("Workstation received both requests and the board closed the link", flush=True)


def board_check(destination_hash):
    RNS.Reticulum(configdir="/var/lib/opi-reticulum", require_shared_instance=True)
    if not RNS.Transport.has_path(destination_hash):
        RNS.Transport.request_path(destination_hash)
    deadline = time.monotonic() + 470
    while not RNS.Transport.has_path(destination_hash):
        if time.monotonic() >= deadline:
            raise TimeoutError("No path to the workstation")
        time.sleep(0.25)
    identity = RNS.Identity.recall(destination_hash)
    endpoint = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, APP, ASPECT)
    if endpoint.hash != destination_hash:
        raise ValueError("Discovered destination does not match the LAN test")
    connected = threading.Event()
    link = RNS.Link(endpoint, established_callback=lambda _: connected.set())
    try:
        if not connected.wait(20):
            raise TimeoutError("Link establishment timed out")
        for size in SIZES:
            challenge = secrets.token_bytes(size)
            receipt = link.request("/echo", data=challenge, timeout=20)
            if not receipt:
                raise RuntimeError("Could not submit echo request")
            deadline = time.monotonic() + 25
            while receipt.get_status() not in (RNS.RequestReceipt.READY, RNS.RequestReceipt.FAILED):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {size}-byte response")
                time.sleep(0.05)
            if receipt.get_response() != challenge:
                raise RuntimeError(f"Incorrect {size}-byte response")
            print(f"PASS: {size}-byte request and byte-identical response", flush=True)
    finally:
        link.teardown()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    roles = cli.add_subparsers(dest="role", required=True)
    roles.add_parser("workstation").add_argument("board", type=IPv4Address)
    roles.add_parser("board").add_argument("destination", type=bytes.fromhex)
    args = cli.parse_args()
    if args.role == "workstation":
        workstation(args.board)
    else:
        board_check(args.destination)
