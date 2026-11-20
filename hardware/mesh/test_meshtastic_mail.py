from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import meshtastic_mail as mail


A = 0x01010101
B = 0x22334402
C = 0x22334403


class SimulatorMail(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = Path(temp.name)
        with mail.database(self.state) as db:
            mail.setup(db)
            db.execute("INSERT INTO device VALUES (1,?,?)", (A, "test"))

    def test_direct_send_and_ack_identity(self):
        with mail.database(self.state) as db:
            for num in (B, C, A, mail.BROADCAST):
                mail.heard(db, A, num, "Node")
            for num in (A, mail.BROADCAST, 0, 42):
                with self.assertRaises(ValueError):
                    mail.queue_send(db, num, "test", 233)
            with self.assertRaises(ValueError):
                mail.queue_send(db, B, "я"*117, 233)
            mail.queue_send(db, B, "Привет", 233)
        client = Mock()
        client.sendText.return_value = SimpleNamespace(id=90)
        mail.dispatch(self.state, client, A)
        client.sendText.assert_called_once_with("Привет", destinationId=B, wantAck=True)
        with mail.database(self.state) as db:
            mail.packet_event(db, A, {"from": B, "to": A, "decoded": {
                "portnum": "ROUTING_APP", "requestId": 90, "routing": {"routeReply": {}}}})
            self.assertEqual(db.execute("SELECT status FROM messages").fetchone()[0], "awaiting ACK")
            for sender, target, req in ((A,A,90), (B,C,90), (C,A,90), (B,A,91), (B,A,90)):
                mail.packet_event(db, A, {"from":sender, "to":target, "decoded":{
                    "portnum":"ROUTING_APP", "requestId":req, "routing":{}}})
                status = db.execute("SELECT status FROM messages").fetchone()[0]
                self.assertEqual(status, "acknowledged" if (sender,target,req)==(B,A,90) else "awaiting ACK")

    def test_address_filter_retries_and_channel(self):
        packet = {"from":B, "to":A, "id":3, "decoded":{"portnum":"TEXT_MESSAGE_APP","text":"test"}}
        with mail.database(self.state) as db:
            for other in (packet, packet, packet | {"to":C}, packet | {"from":A}, packet | {"to":mail.BROADCAST}):
                mail.packet_event(db, A, other)
            self.assertEqual([r[0] for r in db.execute("SELECT kind FROM messages ORDER BY id")], ["direct", "channel 0"])
            self.assertEqual(db.execute("SELECT num FROM nodes").fetchone()[0], B)

    def test_restart_does_not_replay_uncertain_send(self):
        with mail.database(self.state) as db:
            mail.heard(db, A, B)
            mail.queue_send(db, B, "test", 233)
            db.execute("UPDATE messages SET status='submitting'")
            mail.setup(db)
        client = Mock()
        mail.dispatch(self.state, client, A)
        client.sendText.assert_not_called()
        with mail.database(self.state) as db:
            self.assertEqual(db.execute("SELECT status FROM messages").fetchone()[0], "unconfirmed")
            with self.assertRaises(ValueError):
                mail.queue_send(db, B, "offline", 233)

    def test_nodeinfo_discovery_and_negative_ack(self):
        with mail.database(self.state) as db:
            mail.packet_event(db, A, {"from": B, "to": mail.BROADCAST, "decoded": {
                "portnum": "NODEINFO_APP", "user": {"longName": "Peer B"}}})
            self.assertEqual(db.execute("SELECT name FROM nodes WHERE num=?", (B,)).fetchone()[0], "Peer B")
            mail.queue_send(db, B, "test", 233)
        client = Mock()
        client.sendText.return_value = SimpleNamespace(id=555)
        mail.dispatch(self.state, client, A)
        with mail.database(self.state) as db:
            mail.packet_event(db, A, {"from": A, "to": A, "decoded": {
                "portnum": "ROUTING_APP", "requestId": 555, "routing": {"errorReason": "NO_ROUTE"}}})
            self.assertEqual(db.execute("SELECT status FROM messages").fetchone()[0], "failed: NO_ROUTE")


if __name__ == "__main__":
    unittest.main()
