"""Exchange two signed LXMF user messages between independently enrolled contacts."""
import argparse
from ipaddress import IPv4Address
import os
from pathlib import Path
from queue import Empty, Queue
import time

import LXMF
import RNS


def prepare(state):
    state.mkdir(mode=0o700)
    identity = RNS.Identity()
    if not identity.to_file(str(state / "identity")):
        raise OSError("Could not save test identity")
    print(RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity).hex())


def connect(state, host):
    if host is None:
        return RNS.Reticulum(configdir="/var/lib/opi-reticulum", require_shared_instance=True)
    config = state / "reticulum"
    config.mkdir(exist_ok=True)
    (config / "config").write_text(
        "[reticulum]\n  share_instance = no\n  enable_transport = no\n"
        "[stamps]\n  max_workers = 2\n"
        "[interfaces]\n  [[LAN board]]\n    type = TCPClientInterface\n"
        f"    enabled = yes\n    target_host = {host}\n    target_port = 4242\n"
    )
    return RNS.Reticulum(configdir=str(config))


def fields(role, run):
    title = f"LXMF {role}"
    text = "Проверка связи с компьютера." if role == "workstation" else "Плата приняла сообщение."
    return title, f"{text} [{run}]"


def send(router, source, target, role, run):
    title, text = fields(role, run)
    message = LXMF.LXMessage(target, source, text, title, desired_method=LXMF.LXMessage.DIRECT)
    finished = Queue()
    message.register_delivery_callback(finished.put)
    message.register_failed_callback(finished.put)
    router.handle_outbound(message)
    result = finished.get(timeout=100)
    if result.state != LXMF.LXMessage.DELIVERED or result.method != LXMF.LXMessage.DIRECT:
        raise RuntimeError("LXMF did not confirm direct delivery")
    print(f"DELIVERED {message.hash.hex()}", flush=True)
    return message.hash


def receive(inbox, state, source, target, role, run, timeout):
    title, text = fields(role, run)
    try:
        message = inbox.get(timeout=timeout)
    except Empty:
        raise TimeoutError("Timed out waiting for the peer's LXMF message") from None
    if (message.source_hash != source or message.destination_hash != target
            or message.method != LXMF.LXMessage.DIRECT or not message.transport_encrypted
            or message.title != title.encode() or message.content != text.encode()):
        raise RuntimeError("Incoming LXMF envelope or content did not match")
    # A queued packet can precede its sender's announce. Recheck the original
    # signed bytes after peer discovery before accepting it into the inbox.
    if not LXMF.LXMessage.unpack_from_bytes(message.packed).signature_validated:
        raise RuntimeError("Invalid sender signature")
    directory = state / "inbox"
    directory.mkdir(exist_ok=True)
    path = message.write_to_directory(str(directory))
    if not path:
        raise OSError("Could not save the incoming message")
    with open(path, "rb") as saved:
        stored = LXMF.LXMessage.unpack_from_file(saved)
    if not stored or not stored.signature_validated or stored.hash != message.hash:
        raise RuntimeError("Stored message failed verification")
    print(f"RECEIVED {stored.hash.hex()} (signed, UTF-8 matched, inbox reopened)", flush=True)
    return stored.hash


def exchange(args):
    identity = RNS.Identity.from_file(str(args.state / "identity"))
    if identity is None:
        raise ValueError("Initialize this endpoint first")
    connect(args.state, getattr(args, "host", None))
    router = LXMF.LXMRouter(identity=identity, storagepath=str(args.state), autopeer=False)
    source = router.register_delivery_identity(identity, display_name=f"Test {args.role}")
    if args.peer == source.hash:
        raise ValueError("Expected an independent peer")
    inbox = Queue(maxsize=4)

    def incoming(message):
        if message.source_hash == args.peer and message.destination_hash == source.hash:
            inbox.put_nowait(message)

    router.register_delivery_callback(incoming)
    router.announce(source.hash)
    print("Waiting for the peer's Reticulum path and identity", flush=True)
    deadline = time.monotonic() + 840
    requested_at = -float("inf")
    while not (RNS.Transport.has_path(args.peer) and RNS.Identity.recall(args.peer)):
        now = time.monotonic()
        if now >= deadline:
            raise TimeoutError("Peer discovery timed out")
        if now - requested_at >= 60:
            RNS.Transport.request_path(args.peer)
            requested_at = now
        time.sleep(0.25)
    target = RNS.Destination(RNS.Identity.recall(args.peer), RNS.Destination.OUT,
                             RNS.Destination.SINGLE, "lxmf", "delivery")
    if target.hash != args.peer:
        raise ValueError("Discovered contact does not match peer")
    if args.role == "workstation":
        send(router, source, target, args.role, args.run)
        receive(inbox, args.state, target.hash, source.hash, "board", args.run, 120)
    else:
        # The workstation can still be waiting for the board's first stamp.
        receive(inbox, args.state, target.hash, source.hash, "workstation", args.run,
                max(120, deadline - time.monotonic() + 60))
        send(router, source, target, args.role, args.run)


if __name__ == "__main__":
    os.umask(0o077)
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="role", required=True)
    commands.add_parser("init").add_argument("state", type=Path)
    for role in ("workstation", "board"):
        command = commands.add_parser(role)
        command.add_argument("state", type=Path)
        command.add_argument("peer", type=bytes.fromhex)
        command.add_argument("run", help="fresh shared test label")
        if role == "workstation":
            command.add_argument("host", type=IPv4Address)
    args = cli.parse_args()
    if args.role == "init":
        prepare(args.state)
    else:
        exchange(args)
