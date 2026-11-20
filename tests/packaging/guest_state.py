"""Guest-only persistence fixtures. No hardware, sockets to peers or physical sends."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, "/opt/opi-mesh")
import lxmf_mailbox as lx
import meshtastic_mail as mesh

LX = Path("/var/lib/opi-lxmf")
MT = Path("/var/lib/opi-meshtastic-mail")
PEER = 0x22334402
CONTACT = "5061636b616765546573745065657231"
EXPECTED = Path("/var/lib/opi-package-proof/expected.json")


def seed():
    # The lifecycle test exercises the real storage paths with synthetic inputs.
    # Never mark a synthetic incoming LXMF envelope as signature-verified.
    local = bytes.fromhex((LX / "address").read_text().strip())
    incoming = SimpleNamespace(destination_hash=local, source_hash=bytes.fromhex(CONTACT),
                               signature_validated=False, title="Проверка".encode(),
                               content="Входящее LXMF — №1".encode(), hash=sha256(b"pkg-fixture").digest())
    lx.incoming(LX, local, incoming)
    with lx.database(LX) as db:
        lx.save_contact(db, "Контакт Δ", CONTACT)
        number = db.execute("SELECT id FROM contacts WHERE address=?", (CONTACT,)).fetchone()[0]
        lx.queue_message(db, number, "Ответ", "Исходящее LXMF — №2")
    with mesh.database(MT) as db:
        local = db.execute("SELECT num FROM device").fetchone()[0]
        mesh.heard(db, local, PEER, "Сосед B")
        mesh.packet_event(db, local, {"from":PEER, "to":local, "id":4321,
            "decoded":{"portnum":"TEXT_MESSAGE_APP", "text":"Входящее Meshtastic — №3"}})
        mesh.queue_send(db, PEER, "Исходящее Meshtastic — №4", 233)


def snapshot():
    result = {}
    queries = ((LX, "lx", ("SELECT * FROM contacts ORDER BY id", "SELECT * FROM messages ORDER BY id")),
               (MT, "mt", ("SELECT num,name FROM nodes WHERE num=573785090", "SELECT * FROM messages ORDER BY id")))
    for base, prefix, sql in queries:
        con = sqlite3.connect(f"file:{base}/mailbox.sqlite?mode=ro", uri=True)
        try:
            assert con.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            for i, query in enumerate(sql):
                result[f"{prefix}{i}"] = [list(row) for row in con.execute(query)]
        finally:
            con.close()
    for key, path in {"identity":LX / "identity", "address":LX / "address", "spi":Path("/etc/armbian-config/sx1262-spi-hz"),
                     "rns_config":Path("/etc/opi-mesh/reticulum.conf")}.items():
        result[key] = sha256(path.read_bytes()).hexdigest()
    assert [len(result[k]) for k in ("lx0", "lx1", "mt0", "mt1")] == [1, 2, 1, 2]
    assert (Path("/etc/armbian-config/sx1262-spi-hz").read_text() == "500000\n")
    return result


if __name__ == "__main__":
    if sys.argv[1] == "seed":
        seed()
        EXPECTED.write_text(json.dumps(snapshot(), ensure_ascii=False))
    else:
        actual = snapshot()
        expected = json.loads(EXPECTED.read_text())
        assert expected == actual, [k for k in expected if expected[k] != actual.get(k)]
        canonical = json.dumps(actual, sort_keys=True, ensure_ascii=False).encode()
        print("STATE-PASS", sys.argv[1], sha256(canonical).hexdigest(),
              "contacts=1 nodes=1 inbox=2 outbox=2 spi=500000 identities/config=match integrity=ok", flush=True)
