"""Exercise two independent LXMF/RNS nodes through two SX1262 SPI models on Linux."""
from contextlib import ExitStack
import multiprocessing
import os
from pathlib import Path
from queue import Queue
import secrets
import select
import sys
import tempfile
import threading
import time
import tty

HARDWARE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(HARDWARE / name) for name in ("mesh", "reticulum-sx1262", "meshtastic-sx1262")]
sys.path.insert(0, str(HARDWARE.parent / "share/armbian-config"))

import LXMF
import RNS
from RNS.Interfaces.RNodeInterface import RNodeInterface
from check_lxmf_lan import send, receive
from rnode_adapter import Session
from rnode_wire import Decoder
from sx1262_model import Model
from sx1262_tx import Transceiver


def endpoint(role, state, port, control, label):
    # This process has exactly one interface. The serial endpoint is an allocated PTY.
    config = state / "config"
    config.write_text(f"""[reticulum]
  share_instance = no
  enable_transport = no
[stamps]
  max_workers = 1
  destination_value = 8
  destination_cost = 8
[interfaces]
  [[Twin]]
    type = RNodeInterface
    port = {port}
    enabled = yes
    outgoing = yes
    frequency = 433875000
    bandwidth = 125000
    spreadingfactor = 9
    codingrate = 5
    txpower = 0
    flow_control = yes
""")
    RNS.Reticulum(configdir=str(state))
    iface, = RNS.Transport.interfaces
    assert isinstance(iface, RNodeInterface) and iface.online and iface.OUT and iface.port == port
    identity = RNS.Identity()
    router = LXMF.LXMRouter(identity=identity, storagepath=str(state), autopeer=False)
    source = router.register_delivery_identity(identity, display_name=role)
    inbox = Queue()
    router.register_delivery_callback(inbox.put)
    control.send(source.hash)
    peer = control.recv()
    assert peer != source.hash
    router.announce(source.hash)
    deadline = time.monotonic() + 60
    next_announce = time.monotonic() + 5
    while not (RNS.Transport.has_path(peer) and RNS.Identity.recall(peer)):
        now = time.monotonic()
        if now > deadline:
            raise TimeoutError(f"{role} did not discover its peer over RNode")
        if now >= next_announce:
            RNS.Transport.request_path(peer)
            router.announce(source.hash)
            next_announce = now + 5
        time.sleep(.05)
    assert RNS.Transport.next_hop_interface(peer) is iface
    target = RNS.Destination(RNS.Identity.recall(peer), RNS.Destination.OUT,
                             RNS.Destination.SINGLE, "lxmf", "delivery")
    assert target.hash == peer
    if role == "workstation":
        sent = send(router, source, target, role, label)
        received = receive(inbox, state, peer, source.hash, "board", label, 90)
    else:
        received = receive(inbox, state, peer, source.hash, "workstation", label, 90)
        sent = send(router, source, target, role, label)
    control.send((sent, received))
    # Keep both links alive until the other sender has received its proof.
    control.recv()


def serial_loop(master, radio, stop):
    session, decoder = Session(radio), Decoder()
    try:
        while not stop.is_set():
            if select.select([master], [], [], .005)[0]:
                for command, data in decoder.feed(os.read(master, 4096)):
                    reply = session.handle(command, data)
                    if reply:
                        os.write(master, reply)
            incoming = session.poll()
            if incoming:
                os.write(master, incoming)
    finally:
        session.close()


def result(control, timeout):
    if not control.poll(timeout):
        raise TimeoutError("LXMF endpoint timed out")
    return control.recv()


def finish(proc):
    if proc.is_alive():
        proc.terminate()
    proc.join(5)
    if proc.is_alive():
        proc.kill()
        proc.join()
    proc.close()


def run():
    ctx = multiprocessing.get_context("spawn")
    label = secrets.token_hex(56)  # exercise split RNode frames with a fresh message
    models = [Model(2_000_000, Transceiver) for _ in range(2)]
    for sender, peer in zip(models, reversed(models)):
        sender.emit = peer.receive_from_peer
    # These pipes carry addresses, result hashes and the shutdown barrier only.
    controls, children = [], []
    stop = threading.Event()
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        for role, model in zip(("workstation", "board"), models):
            master, slave = os.openpty()
            stack.callback(os.close, master)
            stack.callback(os.close, slave)
            tty.setraw(slave)
            thread = threading.Thread(target=serial_loop, args=(master, model.radio, stop))
            thread.start()
            stack.callback(thread.join)
            stack.callback(stop.set)
            state = Path(tmp, role)
            state.mkdir()
            parent, child = ctx.Pipe()
            stack.callback(parent.close)
            proc = ctx.Process(target=endpoint, args=(role, state, os.ttyname(slave), child, label))
            proc.start()
            child.close()
            stack.callback(finish, proc)
            controls.append(parent)
            children.append(proc)
        left, right = controls
        a, b = [result(control, 30) for control in controls]
        left.send(b)
        right.send(a)
        (a_sent, a_recv), (b_sent, b_recv) = [result(control, 180) for control in controls]
        assert a_sent != b_sent and (a_sent, b_sent) == (b_recv, a_recv)
        for control in controls:
            control.send(None)
        for proc in children:
            proc.join(10)
            assert proc.exitcode == 0, proc.exitcode
        for model in models:
            frames = [op[2:] for op in model.ops if op[0] == 0x0e]
            assert len(frames) == sum(op[0] == 0x83 for op in model.ops)
            assert any(len(frame) == 255 and frame[0] & 1 for frame in frames)
            assert any(op[0] == 0x1e for op in model.ops)
        print(f"PASS: RNS {RNS.__version__}, LXMF {LXMF.__version__}, both DIRECT proofs match signed inbox IDs.")
        print("SX1262 SetTx frames per endpoint:", *(sum(op[0] == 0x83 for op in m.ops) for m in models))


if __name__ == "__main__":
    run()
