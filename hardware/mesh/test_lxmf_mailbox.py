from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

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

    def test_propagation_queue_and_interrupted_collection(self):
        with box.database(self.state) as db:
            box.save_contact(db, "Peer", "aa"*16)
            with self.assertRaisesRegex(ValueError, "propagation node"):
                box.queue_message(db, 1, "offline", "content", True)
            db.execute("UPDATE propagation SET peer=?,sync=2", ("bb"*16,))
            box.queue_message(db, 1, "offline", "content", True)
        box.initialize(self.state)
        router = Mock(PR_COMPLETE=7, PR_NO_PATH=240, propagation_transfer_state=2)
        key = object()
        box.sync_pending(self.state, router, key)
        box.sync_pending(self.state, router, key)
        router.request_messages_from_propagation_node.assert_called_once_with(key)
        router.propagation_transfer_state = 7
        box.sync_pending(self.state, router, key)
        with box.database(self.state) as db:
            self.assertEqual(db.execute("SELECT result FROM sync_result").fetchone()[0], "complete")
            self.assertEqual(db.execute("SELECT sync FROM propagation").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM messages").fetchone()[0], "queued-propagation")

    def test_contact_route_retains_last_announce_without_path(self):
        address = bytes(range(16))
        with box.database(self.state) as db:
            box.save_contact(db, "Peer", address.hex())
        box.track_announces(self.state).received_announce(address, None, None)
        rns = Mock()
        with box.database(self.state) as db:
            for entries, expected in (([], "No known path"), ([dict(hash=address,via=b"b"*16,
                    hops=2,interface="RNodeInterface[Twin]")], "2 hop(s) via")):
                rns.get_path_table.return_value = entries
                with redirect_stdout(StringIO()) as output:
                    box.contact_route(db, 1, rns)
                self.assertIn(expected, output.getvalue())
                self.assertNotIn("not observed", output.getvalue())

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
