"""Text history and directed sends for the private Meshtastic simulator."""
import argparse
from contextlib import closing
from datetime import datetime
import fcntl
import os
from pathlib import Path
from queue import Empty, Queue
import sqlite3
import sys
import time

from mesh_mail_store import database, display, user_text

STATE = Path("/var/lib/opi-meshtastic-mail")
BROADCAST = 0xffffffff
PAGE = 16


def node_id(number):
    return f"!{number:08x}"


def valid_peer(number, local):
    return type(number) is int and 0 < number < BROADCAST and number != local


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS device (slot INTEGER PRIMARY KEY CHECK(slot=1),
            num INTEGER NOT NULL, firmware TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS nodes (num INTEGER PRIMARY KEY, name TEXT NOT NULL, available INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, folder TEXT NOT NULL,
            peer INTEGER NOT NULL, packet INTEGER, kind TEXT NOT NULL, body TEXT NOT NULL,
            created INTEGER NOT NULL, updated INTEGER NOT NULL, status TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS by_packet ON messages(folder,packet,peer);
        CREATE INDEX IF NOT EXISTS by_folder ON messages(folder,id);
    """)
    db.execute("UPDATE nodes SET available=0")
    db.execute("UPDATE messages SET status='unconfirmed' WHERE status IN ('submitting','awaiting ACK')")


def heard(db, local, number, name=""):
    if valid_peer(number, local):
        db.execute("""INSERT INTO nodes VALUES (?,?,1) ON CONFLICT(num) DO UPDATE SET
                   name=COALESCE(NULLIF(excluded.name,''),nodes.name),available=1""", (number, name))


def packet_event(db, local, packet):
    peer, target = packet.get("from"), packet.get("to")
    decoded = packet.get("decoded", {})
    stamp = int(time.time())
    if decoded.get("portnum") == "NODEINFO_APP":
        heard(db, local, peer, decoded.get("user", {}).get("longName", ""))
        return
    if decoded.get("portnum") == "ROUTING_APP":
        request = decoded.get("requestId")
        routing = decoded.get("routing")
        if (target != local or not request or not isinstance(routing, dict)
                or "routeRequest" in routing or "routeReply" in routing):
            return
        reason = routing.get("errorReason", "NONE")
        if reason == "NONE" and not valid_peer(peer, local):
            return
        if peer == local and reason != "NONE":
            # The local firmware may reject a send before it reaches the peer.
            db.execute("""UPDATE messages SET status=?,updated=? WHERE folder='out' AND packet=?
                        AND status='awaiting ACK'""", ("failed: " + str(reason), stamp, request))
        else:
            status = "acknowledged" if reason == "NONE" else "failed: " + str(reason)
            db.execute("""UPDATE messages SET status=?,updated=? WHERE folder='out' AND peer=? AND packet=?
                        AND status IN ('awaiting ACK','unconfirmed') AND updated>=?""",
                       (status, stamp, peer, request, stamp - 600))
        return
    if (decoded.get("portnum") != "TEXT_MESSAGE_APP" or not valid_peer(peer, local)
            or target not in (local, BROADCAST) or not isinstance(decoded.get("text"), str)):
        return
    body = decoded["text"]
    pid = packet.get("id") or None
    kind = "direct" if target == local else f"channel {packet.get('channel', 0)}"
    heard(db, local, peer)
    if pid and db.execute("""SELECT 1 FROM messages WHERE folder='in' AND peer=? AND packet=?
                          AND kind=? AND body=? AND created>=?""",
                          (peer, pid, kind, body, stamp-600)).fetchone():
        return
    db.execute("""INSERT INTO messages(folder,peer,packet,kind,body,created,updated,status)
                  VALUES ('in',?,?,?,?,?,?,'received')""", (peer, pid, kind, body, stamp, stamp))


def queue_send(db, peer, body, limit):
    user_text(body, limit)
    local = db.execute("SELECT num FROM device").fetchone()
    if not local or not valid_peer(peer, local["num"]) or not db.execute(
            "SELECT 1 FROM nodes WHERE num=? AND available=1", (peer,)).fetchone():
        raise ValueError("Select an available remote node.")
    stamp = int(time.time())
    return db.execute("""INSERT INTO messages(folder,peer,kind,body,created,updated,status)
                         VALUES ('out',?,'direct',?,?,?,'queued')""", (peer, body, stamp, stamp)).lastrowid


def dispatch(state, client, local):
    stamp = int(time.time())
    with database(state) as db:
        db.execute("UPDATE messages SET status='unconfirmed' WHERE status='awaiting ACK' AND updated<?", (stamp-120,))
        db.execute("UPDATE messages SET status='expired' WHERE status='queued' AND created<?", (stamp-120,))
        row = db.execute("""SELECT m.* FROM messages m JOIN nodes n ON n.num=m.peer
                            WHERE m.status='queued' AND n.available=1 ORDER BY m.id LIMIT 1""").fetchone()
        if row is None or not valid_peer(row["peer"], local):
            return
        db.execute("UPDATE messages SET status='submitting' WHERE id=?", (row["id"],))
    try:
        result = client.sendText(row["body"], destinationId=row["peer"], wantAck=True)
        packet, status = result.id, "awaiting ACK"
    except Exception as error:
        packet, status = None, "unconfirmed"
        print(f"Submission of message {row['id']} raised {type(error).__name__}", file=sys.stderr, flush=True)
    with database(state) as db:
        db.execute("UPDATE messages SET status=?,packet=?,updated=? WHERE id=?", (status, packet, stamp, row["id"]))


def serve(state):
    from sim_client import connect_simulator
    from pubsub import pub
    from sim_region import advertise, require_sim_namespace

    require_sim_namespace()
    events = Queue(maxsize=256)

    def receive(packet, interface):
        events.put(("packet", packet))

    def node_update(node, interface):
        events.put(("node", node))

    with (state / "service.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with database(state) as db:
            setup(db)
        pub.subscribe(receive, "meshtastic.receive.text")
        pub.subscribe(receive, "meshtastic.receive.user")
        pub.subscribe(receive, "meshtastic.receive.routing")
        pub.subscribe(node_update, "meshtastic.node.updated")
        with closing(connect_simulator()) as client:
            local = client.myInfo.my_node_num
            firmware = client.metadata.firmware_version
            if not local or not firmware:
                raise RuntimeError("Missing simulator metadata.")
            with database(state) as db:
                previous = db.execute("SELECT num FROM device").fetchone()
                if previous and previous["num"] != local:
                    raise RuntimeError("Simulator identity changed; check the configured state directory.")
                db.execute("INSERT OR REPLACE INTO device VALUES (1,?,?)", (local, firmware))
                for n, node in list(client.nodesByNum.items()):
                    heard(db, local, n, node.get("user", {}).get("longName", ""))
            while client.isConnected.is_set() and client._rxThread.is_alive():
                try:
                    kind, data = events.get(timeout=0.5)
                except Empty:
                    pass
                else:
                    with database(state) as db:
                        if kind == "node":
                            heard(db, local, data.get("num"), (data.get("user") or {}).get("longName", ""))
                        else:
                            packet_event(db, local, data)
                request = state / "discover"
                if request.exists():
                    request.unlink()
                    advertise(client)
                dispatch(state, client, local)
            raise ConnectionError("Simulator connection closed.")


def listing(db, folder, before):
    if folder == "nodes":
        rows = db.execute("""SELECT num AS id,name FROM nodes WHERE available=1 AND num<?
                             ORDER BY num DESC LIMIT ?""", (before, PAGE+1)).fetchall()
    else:
        rows = db.execute("""SELECT m.id,m.kind,m.peer,substr(m.body,1,60) AS preview,m.status,n.name
                             FROM messages m LEFT JOIN nodes n ON m.peer=n.num
                             WHERE m.folder=? AND m.id<? ORDER BY m.id DESC LIMIT ?""",
                          (folder, before, PAGE+1)).fetchall()
    for row in rows[:PAGE]:
        if folder == "nodes":
            label = f"{display(row['name'])} [{node_id(row['id'])}]"
        else:
            label = f"{display(row['name']) or node_id(row['peer'])}  {display(row['preview'])} [{row['status']}]"
        print(f"{row['id']}\t{label}")
    if len(rows)>PAGE:
        print(f"more-{rows[PAGE-1]['id']}\tMore entries")


def details(db, folder, number):
    m = db.execute("SELECT * FROM messages WHERE folder=? AND id=?", (folder, number)).fetchone()
    if m is None:
        raise ValueError("Message not found.")
    print(f"{'From' if folder=='in' else 'To'}: {node_id(m['peer'])}")
    print(f"{datetime.fromtimestamp(m['created']):%Y-%m-%d %H:%M:%S}  {m['kind']}")
    print(f"Status: {display(m['status'])}\n\n{display(m['body'], multiline=True)}")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    for name in ("serve", "inspect", "discover"):
        sub.add_parser(name)
    ls = sub.add_parser("list")
    ls.add_argument("folder", choices=("nodes", "in", "out"))
    ls.add_argument("before", type=int, default=2**63-1, nargs="?")
    show = sub.add_parser("show")
    show.add_argument("folder", choices=("in", "out"))
    show.add_argument("number", type=int)
    sub.add_parser("send").add_argument("peer", type=int)
    args = cli.parse_args()
    if args.action == "serve":
        serve(STATE)
        return
    with database(STATE) as db:
        if args.action == "list":
            listing(db, args.folder, args.before)
        elif args.action == "show":
            details(db, args.folder, args.number)
        elif args.action == "discover":
            (STATE / "discover").touch()
            print("Node information requested in the simulator.")
        elif args.action == "inspect":
            row = db.execute("SELECT * FROM device").fetchone()
            if not row:
                raise ValueError("Waiting for simulator metadata.")
            print(f"Simulated node: {node_id(row['num'])}\nFirmware: {row['firmware']}")
        else:
            from meshtastic.protobuf.mesh_pb2 import Constants
            print("Queued message", queue_send(db, args.peer, sys.stdin.read(), Constants.DATA_PAYLOAD_LEN))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as error:
        sys.exit(str(error))
