"""Exercise signed LXMF through SX1262 twins on Linux, optionally via a transport node."""
import argparse
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


def open_rnode(state, port, transport=False):
    # This process has exactly one interface. The serial endpoint is an allocated PTY.
    config = state / "config"
    config.write_text(f"""[reticulum]
  share_instance = no
  enable_transport = {"yes" if transport else "no"}
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
    assert RNS.Reticulum.transport_enabled() == transport
    return iface


def check_isolation(router, source, peer, inbox, control):
    """Probe until B hears both neighbors, then keep checking for a bypass."""
    deadline = time.monotonic() + 60
    end = None
    next_probe = 0
    while end is None or time.monotonic() < end:
        now = time.monotonic()
        if end is None and now > deadline:
            raise TimeoutError("Relay did not hear both endpoint announces")
        if now >= next_probe:
            router.announce(source.hash)
            RNS.Transport.request_path(peer)
            next_probe = now + 4
        if end is None and control.poll():
            if control.recv() != "neighbors seen":
                raise RuntimeError("Missing relay discovery barrier")
            end = now + 10
        assert not RNS.Transport.has_path(peer) and RNS.Identity.recall(peer) is None
        assert inbox.empty()
        time.sleep(.05)
    control.send("isolated")


def endpoint(state, port, control, role, label, isolated):
    iface = open_rnode(state, port)
    identity = RNS.Identity()
    router = LXMF.LXMRouter(identity=identity, storagepath=str(state), autopeer=False)
    source = router.register_delivery_identity(identity, display_name=role)
    inbox = Queue()
    router.register_delivery_callback(inbox.put)
    control.send(source.hash)
    peer, via = control.recv()
    assert peer != source.hash
    if isolated:
        check_isolation(router, source, peer, inbox, control)
        control.recv()
        return
    router.announce(source.hash)
    # RNS schedules forwarded announces against the RNode's normal airtime cap.
    deadline = time.monotonic() + (150 if via is not None else 60)
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
    hops, next_hop = RNS.Transport.hops_to(peer), RNS.Transport.next_hop(peer)
    assert (hops, next_hop) == ((2, via) if via is not None else (1, peer)), (hops, next_hop)
    print(f"{state.name}: hops={hops}, next hop {next_hop.hex()}", flush=True)
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


def relay(state, port, control, transport):
    # This node runs only RNS. The two LXMF identities live at the ends.
    iface = open_rnode(state, port, transport)
    control.send(RNS.Transport.identity.hash)
    neighbors = control.recv()
    deadline = time.monotonic() + 50
    while not all(RNS.Transport.has_path(peer) for peer in neighbors):
        if time.monotonic() >= deadline:
            raise TimeoutError("Middle node did not discover both neighbors")
        time.sleep(.05)
    for peer in neighbors:
        assert RNS.Transport.hops_to(peer) == 1
        assert RNS.Transport.next_hop(peer) == peer
        assert RNS.Transport.next_hop_interface(peer) is iface
    control.send("neighbors seen")
    control.recv()  # endpoints finished probing or exchanging mail
    control.send((RNS.Transport.link_rxb, RNS.Transport.link_txb))


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


def start_node(stack, state, model, target, *args):
    ctx = multiprocessing.get_context("spawn")
    master, slave = os.openpty()
    stack.callback(os.close, master)
    stack.callback(os.close, slave)
    tty.setraw(slave)
    stop = threading.Event()
    thread = threading.Thread(target=serial_loop, args=(master, model.radio, stop))
    thread.start()
    stack.callback(thread.join)
    stack.callback(stop.set)
    state.mkdir()
    parent, child = ctx.Pipe()
    stack.callback(parent.close)
    proc = ctx.Process(target=target, args=(state, os.ttyname(slave), child, *args))
    with child:
        proc.start()
    stack.callback(finish, proc)
    return parent, proc


def run(routed=False, isolated=False):
    label = secrets.token_hex(56)  # exercise split frames with a fresh message
    a, c = (Model(2_000_000, Transceiver) for _ in range(2))
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        root = Path(tmp)
        children = []
        middle = via = None
        if routed:
            b = Model(2_000_000, Transceiver)
            # One radio on B. Its transmissions can be heard by both ends.
            # An end's SetTx can only reach B's RX FIFO.
            a.emit = c.emit = b.receive_from_peer

            def from_middle(frame):
                a.receive_from_peer(frame)
                c.receive_from_peer(frame)

            b.emit = from_middle
            middle, proc = start_node(stack, root / "B", b, relay, not isolated)
            children.append(proc)
            via = result(middle, 30)
            radios = (a, b, c)
        else:
            a.emit, c.emit = c.receive_from_peer, a.receive_from_peer
            radios = (a, c)

        # Pipes carry addresses and acceptance results. Messages and proofs travel over RNode.
        ends = []
        for role, name, model in (("workstation", "A", a), ("board", "C", c)):
            control, proc = start_node(stack, root / name, model, endpoint, role, label, isolated)
            ends.append(control)
            children.append(proc)
        left, right = ends
        addr_a, addr_c = [result(control, 30) for control in ends]
        if middle is not None:
            assert len({via, addr_a, addr_c}) == 3
            middle.send((addr_a, addr_c))
        left.send((addr_c, via))
        right.send((addr_a, via))
        if middle is not None and result(middle, 55) != "neighbors seen":
            raise RuntimeError("Middle node did not confirm both one-hop routes")
        if isolated:
            for control in ends:
                control.send("neighbors seen")
            isolation_results = [result(control, 20) for control in ends]
            assert isolation_results == ["isolated", "isolated"]
        else:
            (a_sent, a_recv), (c_sent, c_recv) = [result(control, 300) for control in ends]
            assert a_sent != c_sent and (a_sent, c_sent) == (c_recv, a_recv)
        if middle is not None:
            middle.send("link counters")
            rx_bytes, tx_bytes = result(middle, 5)
            if isolated:
                assert (rx_bytes, tx_bytes) == (0, 0)
                print("PASS: B heard A and C individually with transport off; both ends remained isolated.")
            else:
                assert rx_bytes > 0 and tx_bytes > 0
                print(f"B {via.hex()}: routed link bytes RX={rx_bytes}, TX={tx_bytes}")
        for control in ends:
            control.send(None)
        for proc in children:
            proc.join(10)
            assert proc.exitcode == 0, proc.exitcode
        if not isolated:
            for model in radios:
                frames = [op[2:] for op in model.ops if op[0] == 0x0e]
                assert len(frames) == sum(op[0] == 0x83 for op in model.ops)
                assert any(len(frame) == 255 and frame[0] & 1 for frame in frames)
                assert any(op[0] == 0x1e for op in model.ops)
            print(f"PASS: RNS {RNS.__version__}, LXMF {LXMF.__version__}, both DIRECT proofs match signed inbox IDs.")
            print("SX1262 SetTx frames per node:", *(sum(op[0] == 0x83 for op in m.ops) for m in radios))


if __name__ == "__main__":
    if not __debug__:
        sys.exit("Acceptance checks require Python assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routed", action="store_true",
                        help="exercise A–B–C with B transport off and then on, using fresh state each time")
    args = parser.parse_args()
    if args.routed:
        run(routed=True, isolated=True)
    run(routed=args.routed)
