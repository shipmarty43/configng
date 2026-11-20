"""Private LXMF text mailbox for the Armbian configurator."""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import unicodedata

STATE = Path("/var/lib/opi-lxmf")
PAGE = 16


@contextmanager
def database(state):
    with closing(sqlite3.connect(state / "mailbox.sqlite", timeout=10)) as db:
        db.row_factory = sqlite3.Row
        with db:
            yield db


def initialize(state):
    with database(state) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY, address TEXT UNIQUE NOT NULL, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, direction TEXT NOT NULL, address TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL,
                status TEXT NOT NULL, hash TEXT, UNIQUE(direction, hash));
            CREATE INDEX IF NOT EXISTS mailbox_folder ON messages(direction, id);
        """)
        # A process may have handed these to LXMF before losing power.
        db.execute("UPDATE messages SET status='unconfirmed' WHERE direction='out' AND status='sending'")


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise ValueError("Enter the 32 hexadecimal digits of the LXMF delivery address.")
    return value.lower()


def display(value, multiline=False):
    # Keep message data out of terminal control sequences and dialog's markup.
    text = "".join(c if (c == "\n" and multiline) or c.isprintable() else " " for c in value)
    return text if multiline else text.replace("\\", "＼")


def user_text(value, limit, required=True):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError("Text is empty.")
    if len(value.encode("utf-8")) > limit or any(
            unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value):
        raise ValueError(f"Enter UTF-8 text of at most {limit} bytes without control characters.")
    return value


def save_contact(db, name, dest):
    dest = address(dest)
    user_text(name, 96)
    if "\n" in name or "\t" in name:
        raise ValueError("Use a single-line contact name.")
    db.execute("""INSERT INTO contacts(address,name) VALUES (?,?)
                  ON CONFLICT(address) DO UPDATE SET name=excluded.name""", (dest, name))
    return dest


def queue_message(db, contact, title, body):
    row = db.execute("SELECT address FROM contacts WHERE id=?", (contact,)).fetchone()
    if row is None:
        raise ValueError("The selected contact is unavailable.")
    user_text(title, 256, required=False)
    user_text(body, 4096)
    return db.execute("""INSERT INTO messages(direction,address,title,body,created,status)
                         VALUES ('out',?,?,?,?, 'queued')""",
                      (row["address"], title, body, int(time.time()))).lastrowid


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
                      WHERE status='queued' AND created < ?""", (int(time.time()) - 600,))
        # One head per destination keeps an unknown address from blocking other contacts.
        pending = db.execute("""SELECT * FROM messages WHERE id IN
                    (SELECT MIN(id) FROM messages WHERE status='queued' GROUP BY address)
                    ORDER BY id""").fetchall()
    for row in pending:
        dest = bytes.fromhex(row["address"])
        identity = RNS.Identity.recall(dest)
        if identity is None or not RNS.Transport.has_path(dest):
            if now - requested.get(dest, -float("inf")) >= 60:
                RNS.Transport.request_path(dest)
                requested[dest] = now
            continue
        target = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        if target.hash != dest:
            raise ValueError("Discovered LXMF destination differs from saved contact.")
        number = row["id"]
        message = LXMF.LXMessage(target, source, row["body"], row["title"], desired_method=LXMF.LXMessage.DIRECT)
        with database(state) as db:
            if not db.execute("UPDATE messages SET status='sending' WHERE id=? AND status='queued'",
                              (number,)).rowcount:
                continue
        message.register_delivery_callback(lambda m, n=number: finish(
            state, n, "delivered" if m.state == LXMF.LXMessage.DELIVERED else "unconfirmed", m))
        message.register_failed_callback(lambda m, n=number: finish(state, n, "failed", m))
        try:
            router.handle_outbound(message)
        except Exception as error:
            finish(state, number, "unconfirmed", message)
            print(f"Could not submit message {number}: {type(error).__name__}", file=sys.stderr, flush=True)


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
        router.announce(source.hash)
        requested = {}
        while True:
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
    subs.add_parser("send").add_argument("contact", type=int)
    args = cli.parse_args()
    if args.action == "serve":
        serve(STATE)
    elif args.action == "address":
        print((STATE / "address").read_text().strip())
    else:
        if not (STATE / "mailbox.sqlite").exists():
            raise ValueError("Start the LXMF mailbox first.")
        with database(STATE) as db:
            if args.action == "list":
                listing(db, args.folder, args.before)
            elif args.action == "show":
                details(db, args.folder, args.number)
            else:
                data = json.load(sys.stdin)
                if args.action == "add-contact":
                    print("Saved contact", save_contact(db, data["name"], data["address"]))
                else:
                    print("Queued message", queue_message(db, args.contact, data["title"], data["body"]))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (KeyError, ValueError, OSError, sqlite3.Error) as error:
        sys.exit(str(error))
