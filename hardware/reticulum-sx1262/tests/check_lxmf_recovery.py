"""Drop RNode fragments and proofs, reboot the relay, then collect offline LXMF."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
import secrets
import tempfile
import threading
import time

from check_lxmf_twin import LXMF, RNS, Model, Transceiver, open_rnode, result, start_node
import lxmf_mailbox as box


def body(tag):
    return "Сообщение с проверкой подписи " + tag * 6


def worker(state, port, control, role):
    open_rnode(state, port, role == "B")
    rns = RNS.Reticulum.get_instance()
    # Keep the recovery test bounded on a slow emulated CPU.
    RNS.Link.KEEPALIVE_MAX = 10
    RNS.Link.KEEPALIVE = 10
    RNS.Link.STALE_TIME = 20
    ident_path = state / "mail.key"
    if ident_path.exists():
        key = RNS.Identity.from_file(str(ident_path))
    else:
        key = RNS.Identity()
        assert key.to_file(str(ident_path))
    box.initialize(state)
    # Reduce only proof-of-work for the isolated propagation test.
    router = LXMF.LXMRouter(identity=key, storagepath=str(state), autopeer=False, propagation_cost=4)
    dest = router.register_delivery_identity(key, display_name=role)
    router.register_delivery_callback(lambda m: box.incoming(state,dest.hash,m))
    RNS.Transport.register_announce_handler(box.track_announces(state))
    if role == "B":
        with box.database(state) as db:
            db.execute("UPDATE propagation SET serve=1 WHERE id=1")
    box.configure_propagation(state,router)
    control.send((dest.hash,RNS.Transport.identity.hash,
                  router.propagation_destination.hash if role=="B" else None))
    requested = {}
    while True:
        if control.poll(.05):
            action,*args = control.recv()
            reply = None
            with box.database(state) as db:
                if action == "quit":
                    return
                if action == "announce":
                    dest.announce(app_data=router.get_announce_app_data(dest.hash))
                    if role=="B":
                        router.propagation_destination.announce(app_data=router.get_propagation_node_app_data())
                elif action == "peer":
                    peer,pn = args
                    box.save_contact(db,"peer",peer.hex())
                    db.execute("UPDATE propagation SET peer=? WHERE id=1",(pn.hex(),))
                    router.set_outbound_propagation_node(pn)
                elif action == "path":
                    with redirect_stdout(StringIO()) as out:
                        box.contact_route(db,1,rns)
                    reply = out.getvalue()
                elif action == "send":
                    tag,propagated=args
                    reply=box.queue_message(db,1,tag,body(tag),propagated)
                elif action == "out":
                    reply=tuple(db.execute("SELECT status,hash FROM messages WHERE id=?",args).fetchone())
                elif action == "in":
                    rows=db.execute("SELECT status,hash,body FROM messages WHERE direction='in' AND title=?",args).fetchall()
                    assert all(r["status"]=="verified" and r["body"]==body(args[0]) for r in rows)
                    reply=[r["hash"] for r in rows]
                elif action == "repeat":
                    # Re-send the very same signed LXMF envelope on its actual RNS link.
                    msg=next(m for m in router.pending_outbound if m.title_as_string()==args[0])
                    RNS.Packet(router.direct_links[msg.destination_hash],msg.packed).send()
                elif action == "sync":
                    db.execute("UPDATE propagation SET sync=1 WHERE id=1")
                elif action == "stored":
                    reply=len(router.propagation_entries)
            control.send(reply)
        box.sync_pending(state,router,key)
        box.dispatch(state,router,dest,requested)


def call(c, *args):
    c.send(args)
    return result(c, 30)


def wait(fn, seconds=120):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=fn()
        if value:
            return value
        time.sleep(.15)
    raise TimeoutError(f"Timed out at {fn.__code__.co_firstlineno}")


class Fault:
    def __init__(self, deliver):
        self.deliver=deliver
        self.mode=None
        self.split=None
        self.dropped=threading.Event()

    def emit(self, frame):
        # RNode header followed by an RNS packet. A continuation has no RNS header.
        if self.split is not None and frame[0]==self.split:
            self.split=None
            self.dropped.set()
            return
        raw=frame[1:]
        if len(raw)>18:
            context_index=34 if raw[0]&0x40 else 18
            kind=raw[0]&3
            if len(raw)>context_index and raw[context_index]==0 and (raw[0]>>2)&3==RNS.Destination.LINK:
                if self.mode=="fragment" and frame[0]&1 and len(frame)==255 and kind==RNS.Packet.DATA:
                    self.split=frame[0]
                if self.mode=="proof" and kind==RNS.Packet.PROOF:
                    self.dropped.set()
                    return
        self.deliver(frame)


def run():
    with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
        root=Path(temp)
        controls={}
        children={}
        lifetimes={}
        radios={}
        def start(role):
            life=stack.enter_context(ExitStack())
            model=Model(2_000_000,Transceiver)
            radios[role]=model
            if role=="B":
                def forward(frame):
                    for endpoint in ("A","C"):
                        if endpoint in radios:
                            radios[endpoint].receive_from_peer(frame)
                model.emit=forward
            else:
                def forward(frame):
                    if "B" in radios:
                        radios["B"].receive_from_peer(frame)
                fault=Fault(forward)
                model.emit=fault.emit
            ctrl, proc=start_node(life,root/role,model,worker,role)
            controls[role],children[role],lifetimes[role]=ctrl,proc,life
            return result(ctrl,40), (fault if role!="B" else None)
        def stop(role):
            radios.pop(role)
            children[role].kill()
            lifetimes.pop(role).close()
        b,_=start("B")
        a,forward=start("A")
        c,reverse=start("C")
        A,B,C=(controls[n] for n in "ABC")
        call(A,"peer",c[0],b[2])
        call(C,"peer",a[0],b[2])
        def discover():
            via=f"2 hop(s) via {b[1].hex()}"
            next_announce = 0
            def ready():
                nonlocal next_announce
                if time.monotonic() >= next_announce:
                    for ctrl in (A,C,B):
                        call(ctrl,"announce")
                    next_announce = time.monotonic() + 12
                return via in call(A,"path") and via in call(C,"path")
            wait(ready,150)
            print("Two-hop routes via", b[1].hex(), flush=True)
        discover()
        tag=secrets.token_hex(13)
        # First split datagram is partially lost on A -> B. Kill B while A awaits delivery.
        forward.mode="fragment"
        num=call(A,"send",tag,False)
        assert forward.dropped.wait(80), "no second data fragment dropped"
        assert call(A,"out",num)[0]=="sending" and call(C,"in",tag)==[]
        stop("B")
        forward.mode=None
        restarted,_=start("B")
        assert restarted==b
        B=controls["B"]
        discover()
        # Use the normal link timeout/retry logic, leaving both endpoints running.
        second=secrets.token_hex(13)
        reply=call(C,"send",second,False)
        wait(lambda: call(C,"out",reply)[0]=="delivered",210)
        assert call(A,"in",second)==[call(C,"out",reply)[1]]
        status=call(A,"out",num)[0]
        assert status!="delivered" or len(call(C,"in",tag))==1
        print("PASS split fragment dropped; relay identity and two-hop route recovered; interrupted row:",status,flush=True)
        # Prove the reverse loss is distinct from losing the original message.
        tag=secrets.token_hex(13)
        reverse.mode="proof"
        num=call(A,"send",tag,False)
        assert reverse.dropped.wait(90), "no delivery proof dropped"
        wait(lambda: call(C,"in",tag))
        assert call(A,"out",num)[0]=="sending"
        call(A,"repeat",tag)
        time.sleep(1)
        assert len(call(C,"in",tag))==1 and call(A,"out",num)[0]!="delivered"
        stop("A")
        a2,_=start("A")
        assert a2[0]==a[0]
        A=controls["A"]
        assert call(A,"out",num)[0]=="unconfirmed"
        reverse.mode=None
        print("PASS missing proof, verified inbox, duplicate suppressed, restored outbox unconfirmed",flush=True)
        call(A,"peer",c[0],b[2])
        discover()
        stop("C")
        tag=secrets.token_hex(13)
        n=call(A,"send",tag,True)
        wait(lambda: call(A,"out",n)[0]=="accepted-by-node" and call(B,"stored")>0,180)
        sent=call(A,"out",n)[1]
        stop("B")
        again,_=start("B")
        assert again==b
        B=controls["B"]
        assert call(B,"stored")>0
        c2,_=start("C")
        assert c2[0]==c[0]
        C=controls["C"]
        call(C,"peer",a[0],b[2])
        discover()
        call(C,"sync")
        wait(lambda: call(C,"in",tag)==[sent],180)
        call(C,"sync")
        time.sleep(2)
        assert call(C,"in",tag)==[sent] and call(A,"out",n)[0]=="accepted-by-node"
        print("PASS offline C, persistent B store, signed retrieval:",sent,flush=True)


if __name__=="__main__":
    if not __debug__:
        raise RuntimeError("Assertions required")
    run()
