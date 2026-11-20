from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import lxmf_mailbox as box


class Mailbox(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        box.initialize(self.state)

    def test_contact_selection_and_crash_recovery(self):
        with box.database(self.state) as db:
            for peer in ("aa", "bb"):
                box.save_contact(db, "Peer", peer * 16)
            box.save_contact(db, "New name", "BB" * 16)
            one = box.queue_message(db, 2, "", "Привет")
            two = box.queue_message(db, 1, "Wait", "Later")
            db.execute("UPDATE messages SET status='sending' WHERE id=?", (one,))
            with self.assertRaises(ValueError):
                box.queue_message(db, 42, "", "Wrong recipient")
            with self.assertRaises(ValueError):
                box.queue_message(db, 2, "", "   ")
        box.initialize(self.state)
        with box.database(self.state) as db:
            rows = db.execute("SELECT id,address,status FROM messages ORDER BY id").fetchall()
            self.assertEqual([tuple(r) for r in rows], [(one, "bb"*16, "unconfirmed"), (two, "aa"*16, "queued")])

    def test_inbox_deduplication_and_terminal_text(self):
        local, peer = bytes(16), bytes(range(16))
        msg = SimpleNamespace(destination_hash=local, source_hash=peer, signature_validated=True,
                              title=b"subject\tline", content="Строка\npath\\file\x1b".encode(), hash=bytes(32))
        box.incoming(self.state, peer, msg)
        box.incoming(self.state, local, msg)
        box.incoming(self.state, local, msg)
        with box.database(self.state) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            out = StringIO()
            with redirect_stdout(out):
                box.details(db, "in", 1)
            self.assertIn("Status: verified", out.getvalue())
            self.assertIn("Строка\npath\\file", out.getvalue())
            self.assertNotIn("\x1b", out.getvalue())
            with self.assertRaises(ValueError):
                box.details(db, "out", 1)
        msg.hash, msg.signature_validated = b"1"*32, False
        box.incoming(self.state, local, msg)
        with box.database(self.state) as db:
            self.assertEqual(db.execute("SELECT status FROM messages WHERE id=2").fetchone()[0], "unverified")

    def test_pagination_uses_stable_ids(self):
        with box.database(self.state) as db:
            for i in range(20):
                box.save_contact(db, f"Name {i}", f"{i:032x}")
            out = StringIO()
            with redirect_stdout(out):
                box.listing(db, "contacts", 21)
            self.assertIn("more-5\tOlder entries", out.getvalue())
            with self.assertRaises(ValueError):
                box.save_contact(db, "Mixed\nlines", "a"*32)
            with self.assertRaises(ValueError):
                box.save_contact(db, "Name", "not an address")
            out = StringIO()
            with redirect_stdout(out):
                box.listing(db, "contacts", 5)
            self.assertEqual(len(out.getvalue().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
