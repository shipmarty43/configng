"""Private LXMF text mailbox for the Armbian configurator."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from mesh_mail_store import database, display, user_text

STATE = Path("/var/lib/opi-lxmf")
PAGE = 16


def ensure_propagation_schema(db):
    db.executescript("""
            CREATE TABLE IF NOT EXISTS propagation (
                id INTEGER PRIMARY KEY CHECK(id=1), serve INTEGER NOT NULL DEFAULT 0,
                peer TEXT, sync INTEGER NOT NULL DEFAULT 0);
            INSERT OR IGNORE INTO propagation(id) VALUES (1);
            CREATE TABLE IF NOT EXISTS last_announce (address TEXT PRIMARY KEY, heard INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sync_result (
                id INTEGER PRIMARY KEY CHECK(id=1), result TEXT NOT NULL);
            """)


def initialize(state):
    with database(state) as db:
        ensure_propagation_schema(db)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY, address TEXT UNIQUE NOT NULL, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, direction TEXT NOT NULL, address TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL,
                status TEXT NOT NULL, hash TEXT, UNIQUE(direction, hash));
            CREATE INDEX IF NOT EXISTS mailbox_folder ON messages(direction, id);
        """)
        db.execute("UPDATE propagation SET sync=1 WHERE sync=2")
        # A process may have handed these to LXMF before losing power.
        db.execute("UPDATE messages SET status='unconfirmed' WHERE direction='out' AND status='sending'")


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise ValueError("Enter the 32 hexadecimal digits of the LXMF delivery address.")
    return value.lower()


def save_contact(db, name, dest):
    dest = address(dest)
    user_text(name, 96)
    if "\n" in name or "\t" in name:
        raise ValueError("Use a single-line contact name.")
    db.execute("""INSERT INTO contacts(address,name) VALUES (?,?)
                  ON CONFLICT(address) DO UPDATE SET name=excluded.name""", (dest, name))
    return dest


def queue_message(db, contact, title, body, propagated=False):
    row = db.execute("SELECT address FROM contacts WHERE id=?", (contact,)).fetchone()
    if row is None:
        raise ValueError("The selected contact is unavailable.")
    user_text(title, 256, required=False)
    user_text(body, 4096)
    if propagated and not db.execute("SELECT peer FROM propagation WHERE id=1").fetchone()[0]:
        raise ValueError("Select a remote propagation node first.")
    return db.execute("""INSERT INTO messages(direction,address,title,body,created,status)
                         VALUES ('out',?,?,?,?,?)""",
                      (row["address"], title, body, int(time.time()), "queued-propagation" if propagated else "queued")).lastrowid


def incoming(state, local, message):
    if message.destination_hash != local:
        return
    # An unknown signing key must never be displayed as a verified sender.
    verification = "verified" if message.signature_validated else "unverified"
    with database(state) as db:
        db.execute("""INSERT INTO messages(direction,address,title,body,created,status,hash)
                      VALUES ('in',?,?,?,?,?,?) ON CONFLICT(direction,hash) DO NOTHING""",
                   (message.source_hash.hex(), message.title.decode("utf-8", "replace"),
                    message.content.decode("utf-8", "replace"), int(time.time()),
                    verification, message.hash.hex()))


def finish(state, number, status, message):
    with database(state) as db:
        db.execute("UPDATE messages SET status=?,hash=? WHERE id=? AND status='sending'",
                   (status, message.hash.hex() if message.hash else None, number))


def dispatch(state, router, source, requested):
    import LXMF
    import RNS

    now = time.monotonic()
    with database(state) as db:
        db.execute("""UPDATE messages SET status='expired'
                      WHERE status IN ('queued','queued-propagation') AND created < ?""", (int(time.time()) - 600,))
        # One head per destination keeps an unknown address from blocking other contacts.
        pending = db.execute("""SELECT * FROM messages WHERE id IN
                    (SELECT MIN(id) FROM messages WHERE status IN ('queued','queued-propagation') GROUP BY address,status)
                    ORDER BY id""").fetchall()
    for row in pending:
        dest = bytes.fromhex(row["address"])
        identity = RNS.Identity.recall(dest)
        propagated = row["status"] == "queued-propagation"
        route = router.get_outbound_propagation_node() if propagated else dest
        if not route:
            continue
        needed = dest if identity is None else route
        if identity is None or not RNS.Transport.has_path(route):
            if now - requested.get(needed, -float("inf")) >= 60:
                RNS.Transport.request_path(needed)
                requested[needed] = now
            continue
        target = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        if target.hash != dest:
            raise ValueError("Discovered LXMF destination differs from saved contact.")
        number = row["id"]
        message = LXMF.LXMessage(target, source, row["body"], row["title"], desired_method=LXMF.LXMessage.PROPAGATED if propagated else LXMF.LXMessage.DIRECT)
        with database(state) as db:
            if not db.execute("UPDATE messages SET status='sending' WHERE id=? AND status=?",
                              (number,row["status"])).rowcount:
                continue
        def completed(m, n=number):
            status = "unconfirmed"
            if m.method == LXMF.LXMessage.DIRECT and m.state == LXMF.LXMessage.DELIVERED:
                status = "delivered"
            elif m.method == LXMF.LXMessage.PROPAGATED and m.state == LXMF.LXMessage.SENT:
                status = "accepted-by-node"
            finish(state, n, status, m)
        message.register_delivery_callback(completed)
        message.register_failed_callback(lambda m, n=number: finish(state, n, "unconfirmed", m))
        try:
            router.handle_outbound(message)
        except Exception as error:
            finish(state, number, "unconfirmed", message)
            print(f"Could not submit message {number}: {type(error).__name__}", file=sys.stderr, flush=True)


def configure_propagation(state, router):
    with database(state) as db:
        config = db.execute("SELECT * FROM propagation WHERE id=1").fetchone()
    if config["peer"]:
        router.set_outbound_propagation_node(bytes.fromhex(config["peer"]))
    if config["serve"]:
        router.set_message_storage_limit(megabytes=16)
        router.enable_propagation()
        router.announce_propagation_node()


def sync_pending(state, router, key):
    with database(state) as db:
        pending = db.execute("SELECT sync FROM propagation WHERE id=1").fetchone()[0]
        if not pending:
            return
        if not router.get_outbound_propagation_node():
            return
        if pending == 1:
            router.request_messages_from_propagation_node(key)
            db.execute("UPDATE propagation SET sync=2 WHERE id=1")
            return
        stage = router.propagation_transfer_state
        if stage == router.PR_COMPLETE:
            result = "complete"
        elif stage >= router.PR_NO_PATH:
            result = f"failed (LXMF state 0x{stage:02x})"
        else:
            return
        db.execute("INSERT OR REPLACE INTO sync_result VALUES (1,?)", (result,))
        db.execute("UPDATE propagation SET sync=0 WHERE id=1")


def track_announces(state):
    class DeliveryAnnounces:
        aspect_filter = "lxmf.delivery"

        def received_announce(self, destination_hash, announced_identity, app_data):
            with database(state) as db:
                db.execute("""INSERT OR REPLACE INTO last_announce(address,heard)
                           SELECT address,? FROM contacts WHERE address=?""",
                           (int(time.time()),destination_hash.hex()))
    return DeliveryAnnounces()


def contact_route(db, contact, rns):
    row = db.execute("""SELECT c.address,a.heard FROM contacts c LEFT JOIN last_announce a
                     ON a.address=c.address WHERE c.id=?""", (contact,)).fetchone()
    if row is None:
        raise ValueError("Unknown contact")
    dest = bytes.fromhex(row["address"])
    entry = next((p for p in rns.get_path_table() if p["hash"] == dest), None)
    heard = datetime.fromtimestamp(row["heard"]).isoformat(timespec="seconds") if row["heard"] else "not observed"
    if entry:
        print(f"Known path: {entry['hops']} hop(s) via {entry['via'].hex()}")
        print("Interface:", display(entry["interface"]))
    else:
        print("No known path")
    print("Last delivery announce observed:", heard)


def serve(state):
    import LXMF
    import RNS

    with (state / "service.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initialize(state)
        RNS.Reticulum(configdir="/var/lib/opi-reticulum", require_shared_instance=True)
        path = state / "identity"
        if not path.exists():
            key = RNS.Identity()
            temp = state / ".identity.new"
            if not key.to_file(str(temp)):
                raise OSError("Could not save mailbox identity.")
            with temp.open("rb") as file:
                os.fsync(file.fileno())
            os.replace(temp, path)
            parent = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        key = RNS.Identity.from_file(str(path))
        if key is None:
            raise ValueError("Could not load the existing mailbox identity.")
        router = LXMF.LXMRouter(identity=key, storagepath=str(state), autopeer=False)
        source = router.register_delivery_identity(key, display_name="Orange Pi mailbox")
        address_file = state / ".address.new"
        address_file.write_text(source.hexhash + "\n")
        os.replace(address_file, state / "address")
        router.register_delivery_callback(lambda m: incoming(state, source.hash, m))
        RNS.Transport.register_announce_handler(track_announces(state))
        configure_propagation(state, router)
        router.announce(source.hash)
        requested = {}
        while True:
            sync_pending(state, router, key)
            dispatch(state, router, source, requested)
            time.sleep(1)


def listing(db, folder, before):
    if folder == "contacts":
        rows = db.execute("""SELECT id,name,address FROM contacts WHERE id < ?
                             ORDER BY id DESC LIMIT ?""", (before, PAGE + 1)).fetchall()
    else:
        rows = db.execute("""SELECT m.id,m.created,m.status,
                    substr(COALESCE(NULLIF(m.title,''),m.body),1,60) AS summary,
                    COALESCE(c.name,m.address) AS name FROM messages m
                    LEFT JOIN contacts c ON c.address=m.address WHERE m.direction=? AND m.id < ?
                    ORDER BY m.id DESC LIMIT ?""", (folder, before, PAGE + 1)).fetchall()
    for row in rows[:PAGE]:
        if folder == "contacts":
            label = f"{display(row['name'])} [{row['address']}]"
        else:
            title = display(row["summary"])
            stamp = datetime.fromtimestamp(row["created"]).strftime("%m-%d %H:%M")
            label = f"{stamp}  {display(row['name'])[:32]}  {title}  [{row['status']}]"
        print(f"{row['id']}\t{label}")
    if len(rows) > PAGE:
        print(f"more-{rows[PAGE-1]['id']}\tOlder entries")


def details(db, folder, number):
    row = db.execute("""SELECT m.*, c.name FROM messages m LEFT JOIN contacts c ON m.address=c.address
                        WHERE m.id=? AND m.direction=?""", (number, folder)).fetchone()
    if row is None:
        raise ValueError("Message not found.")
    who = "From" if folder == "in" else "To"
    print(f"{who}: {display(row['name'] or '')} [{row['address']}]")
    print(f"Status: {row['status']}")
    print(f"Title: {display(row['title'])}\n\n{display(row['body'], multiline=True)}")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    subs = cli.add_subparsers(dest="action", required=True)
    for action in ("serve", "address", "add-contact"):
        subs.add_parser(action)
    ls = subs.add_parser("list")
    ls.add_argument("folder", choices=("contacts", "in", "out"))
    ls.add_argument("before", type=int, default=2**63-1, nargs="?")
    show = subs.add_parser("show")
    show.add_argument("folder", choices=("in", "out"))
    show.add_argument("number", type=int)
    for action in ("send","send-propagated","route"):
        subs.add_parser(action).add_argument("contact", type=int)
    for action in ("prop-status","prop-on","prop-off","sync"):
        subs.add_parser(action)
    subs.add_parser("prop-peer").add_argument("node")
    args = cli.parse_args()
    if args.action == "serve":
        serve(STATE)
    elif args.action == "address":
        print((STATE / "address").read_text().strip())
    else:
        if not (STATE / "mailbox.sqlite").exists():
            raise ValueError("Start the LXMF mailbox first.")
        with database(STATE) as db:
            if args.action.startswith("prop-") or args.action in ("sync", "send-propagated", "route"):
                ensure_propagation_schema(db)
            if args.action == "route":
                import RNS
                contact_route(db,args.contact,RNS.Reticulum(configdir="/var/lib/opi-reticulum",require_shared_instance=True))
            elif args.action == "prop-status":
                cfg = db.execute("SELECT * FROM propagation WHERE id=1").fetchone()
                print("Local propagation node:", "on" if cfg["serve"] else "off")
                if cfg["serve"]:
                    import RNS
                    key = RNS.Identity.from_file(str(STATE/"identity"))
                    print("Local node address:",RNS.Destination.hash_from_name_and_identity("lxmf.propagation",key).hex())
                print("Remote propagation node:", cfg["peer"] or "unset")
                last = db.execute("SELECT result FROM sync_result WHERE id=1").fetchone()
                print("Collection:", "pending" if cfg["sync"] else (last[0] if last else "not requested"))
            elif args.action in ("prop-on","prop-off"):
                db.execute("UPDATE propagation SET serve=? WHERE id=1", (args.action=="prop-on",))
            elif args.action == "prop-peer":
                db.execute("UPDATE propagation SET peer=?,sync=0 WHERE id=1", (address(args.node) if args.node!="off" else None,))
            elif args.action == "sync":
                if not db.execute("UPDATE propagation SET sync=CASE WHEN sync=2 THEN 2 ELSE 1 END WHERE id=1 AND peer IS NOT NULL").rowcount:
                    raise ValueError("Set the remote propagation node first")
                print("Collection requested")
            elif args.action == "list":
                listing(db, args.folder, args.before)
            elif args.action == "show":
                details(db, args.folder, args.number)
            else:
                data = json.load(sys.stdin)
                if args.action == "add-contact":
                    print("Saved contact", save_contact(db, data["name"], data["address"]))
                else:
                    print("Queued message", queue_message(db, args.contact, data["title"], data["body"], args.action=="send-propagated"))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (KeyError, ValueError, OSError, sqlite3.Error) as error:
        sys.exit(str(error))
