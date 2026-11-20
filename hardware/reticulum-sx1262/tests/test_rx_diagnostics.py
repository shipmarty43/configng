from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch
import os

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(root/"share/armbian-config")]
from rnode_metrics import RxMetrics, Publisher
from rnode_wire import Decoder, split_frames
from sx1262_rx import Reception
from sx1262_diagnostics import read_snapshot, rx_lines


class Diagnostics(unittest.TestCase):
    def setUp(self):
        self.rx = RxMetrics()

    def frame(self, data, tick, rssi=-103.5, quarters=-29):
        return self.rx.consume(Reception(data, 2, rssi, quarters), tick)

    def test_wire_exact_for_every_snr_byte(self):
        for raw in range(256):
            signed = raw if raw < 128 else raw-256
            wire = self.frame(b"\xb0ok", 10, quarters=signed)
            self.assertEqual(list(Decoder().feed(wire)), [(0x23,b"\x36"), (0x24,bytes([raw])), (0,b"ok")])
            self.assertEqual(self.rx.last["snr_db"], signed/4)
        self.assertEqual(self.rx.packets, 256)

    def test_errors_and_incomplete_never_replace_last_sample(self):
        a, b = split_frames(b"x"*255, 2)
        self.assertIn("no complete packet", rx_lines(self.rx.snapshot() | {"spi_hz":2000000}, 10)[-1])
        self.frame(a, 1)
        self.rx.consume(Reception(b"", 0x62), 2)
        self.assertEqual((self.rx.crc, self.rx.header_errors, self.rx.reassembly.abandoned), (1,1,1))
        self.assertIsNone(self.rx.last)
        self.frame(b, 3)
        self.assertEqual(self.rx.reassembly.orphans, 1)
        self.frame(a, 4, -90, 12); self.frame(b, 5, -81.5, 0)
        self.assertEqual(self.rx.last, dict(at=5, rssi_dbm=-81.5, snr_db=0))
        self.frame(a, 6)
        self.rx.reassembly.expire(17)  # no additional traffic
        self.assertEqual(self.rx.reassembly.abandoned, 2)
        self.assertFalse(self.rx.snapshot()["pending"])
        self.assertEqual(self.rx.packets, 1)
        self.assertEqual(self.rx.last["at"], 5)

    def test_snapshot_is_scoped_to_live_worker_and_age(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, INVOCATION_ID="test-instance"):
            pub = Publisher(directory, 500000)
            unit = dict(ActiveState="active",SubState="running",MainPID=str(os.getpid()),InvocationID="test-instance")
            pub.update(self.rx, 5)
            self.assertIsNone(read_snapshot(pub.path,unit,5)["last"])
            self.frame(b"\xb0ok", 6)
            pub.update(self.rx, 7)
            view = rx_lines(read_snapshot(pub.path,unit,8), 8)
            self.assertIn("-103.5 dBm", view[-1]); self.assertIn("-7.25 dB", view[-1])
            for stale, now in ((unit,20),(unit|{"InvocationID":"old"},8),(unit|{"MainPID":"0"},8),
                               (unit|{"ActiveState":"inactive"},8)):
                with self.assertRaises(ValueError): read_snapshot(pub.path,stale,now)

    def test_unavailable_runtime_directory_preserves_stats_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, INVOCATION_ID="instance"):
            path = Path(directory)/"runtime"
            pub = Publisher(path, 2000000)
            with redirect_stderr(StringIO()) as errors:
                pub.update(self.rx, 1)
                self.frame(b"\x00packet", 2, 0.0, 0)
                pub.update(self.rx, 2)
            self.assertEqual(len(errors.getvalue().splitlines()), 1)
            path.mkdir()
            pub.update(self.rx, 3)
            unit = dict(ActiveState="active", SubState="running", MainPID=str(os.getpid()), InvocationID="instance")
            report = rx_lines(read_snapshot(pub.path, unit, 3), 3)
            self.assertIn("RSSI: 0 dBm", report[-1])
            self.assertIn("SNR: 0 dB", report[-1])


if __name__=="__main__":
    unittest.main()
