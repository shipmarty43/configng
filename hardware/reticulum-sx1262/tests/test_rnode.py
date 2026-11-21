from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/"meshtastic-sx1262"),
              str(Path(__file__).resolve().parents[3]/"share/armbian-config")]
import sx1262_spi
from sx1262_rx import RD, WR, TRANSFER, Spi
from rnode_wire import Decoder, Reassembly, kiss, split_frames
from rnode_adapter import Session, PARAMS
from sx1262_model import Model
from sx1262_tx import Transceiver


class Wire(unittest.TestCase):
    def test_escape_chunking_overflow_and_resync(self):
        d=Decoder()
        p=b"\xdb\xc0"*254
        stream=kiss(0,p)
        result=[]
        for byte in stream: result.extend(d.feed(bytes([byte])))
        self.assertEqual(result,[(0,p)])
        self.assertEqual(list(d.feed(b"\xc0\x00\xdb\x02bad\xc0"+kiss(0,p+b"x")+kiss(0,b"new"))),[(0,b"new")])

    def test_split_replacement_crc_and_timeout(self):
        r=Reassembly()
        payload=b"x"*254+b"y"*4
        a,b=split_frames(payload,5); c,d=split_frames(payload,7)
        self.assertIsNone(r.accept(a,0)); self.assertIsNone(r.accept(c,1))
        self.assertEqual(r.accept(d,2),payload)
        self.assertIsNone(r.accept(a,3)); self.assertIsNone(r.accept(b,14))
        self.assertIsNone(r.accept(a,15)); self.assertIsNone(r.accept(b"",16))
        self.assertIsNone(r.accept(b,17))
        self.assertEqual(r.accept(b"\x30new",18),b"new")
        self.assertIsNone(r.accept(a,19)); self.assertEqual(r.accept(b,20),payload)

    def test_strict_configuration_and_tx_refusal(self):
        from sx1262_rx import Receiver
        hw=Mock(); hw.send.side_effect=PermissionError
        session=Session(hw)
        self.assertEqual(session.handle(6,b"\1"),kiss(0x90,b"\1"))
        for cmd,value in PARAMS.items(): self.assertEqual(session.handle(cmd,value),kiss(cmd,value))
        self.assertEqual(session.handle(6,b"\1"),kiss(6,b"\1"))
        self.assertEqual(session.handle(0,b"hello"),kiss(0x90,b"\2"))
        self.assertEqual(session.handle(4,b"\x0a"),kiss(0x90,b"\1"))
        hw.off.assert_called_once()
        spi,pins=Mock(),Mock()
        radio=Receiver(spi,pins)
        for op in (0x83,0xd1,0xd2,0xc5,0x0e):
            with self.assertRaises(ValueError): radio.command(op)
        with self.assertRaises(PermissionError): radio.send(b"tx")
        spi.transfer.assert_not_called()

    def test_high_speed_reaches_rnode_ioctl(self):
        settings = {}
        transfers = []
        def ioctl(fd, request, data):
            if request == WR | (TRANSFER.size << 16):
                transfers.append(TRANSFER.unpack(data)[3])
                return TRANSFER.unpack(data)[2]
            if request & RD == RD:
                data[:] = settings[request & 0xff]
            else:
                settings[request & 0xff] = bytes(data)
            return 0
        spi = Spi(-1, 16_000_000, ioctl=ioctl)
        spi.transfer(bytes([0xc0, 0]))
        self.assertEqual(transfers, [16_000_000])

    def test_spi_setting_and_bad_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            setting=Path(tmp)/'rate'; dt=Path(tmp)/'cell'; dt.write_bytes((800000).to_bytes(4,'big'))
            cap=sx1262_spi.ceiling(dt)
            self.assertEqual(sx1262_spi.selected(cap,setting),800000)
            sx1262_spi.save("500000",cap,setting)
            for value in ("0","-1","0x100","500 kHz","800001","500000\n1"):
                with self.assertRaises(ValueError): sx1262_spi.save(value,cap,setting)
                self.assertEqual(sx1262_spi.selected(cap,setting),500000)
            sx1262_spi.save("default",cap,setting); self.assertFalse(setting.exists())
        def wrong(fd,req,arg):
            if isinstance(arg,bytearray): arg[0]=7
            return 0
        with self.assertRaisesRegex(OSError,"readback"):
            Spi(-1,500000,ioctl=wrong)


class Transmission(unittest.TestCase):
    def setUp(self):
        self.model = Model(500_000, Transceiver)
        self.session = Session(self.model.radio)
        for cmd, value in PARAMS.items():
            self.session.handle(cmd, value)
        self.session.handle(6, b"\x01")

    def test_datagram_limits_and_fragment_sequence_wrap(self):
        radio = self.model.radio
        radio.sequence = 15
        for length in (0, 509):
            with self.assertRaises(ValueError):
                radio.send(bytes(length))
        self.assertFalse(any(op[0] == 0x83 for op in self.model.ops))
        for length, header in ((508, 0xf1), (254, 0)):
            payload = (bytes(range(256)) * 2)[:length]
            self.assertEqual(self.session.handle(0, payload), kiss(0x0f, b"\x01"))
            for start in range(0, length, 254):
                self.assertEqual(self.model.out.get_nowait(), bytes([header]) + payload[start:start+254])
            self.assertTrue(self.model.out.empty())
            self.assertEqual(self.model.mode, "rx")

    def test_timeout_and_missing_irq_do_not_ack_partial_datagram(self):
        model = self.model
        for outcome in (0x0200, 0):
            with self.subTest(irq=outcome):
                def fail_second(frame):
                    model.out.put(frame)
                    model.tx_result = outcome

                model.emit = fail_second
                model.radio.HOST_TIMEOUT = .02
                payload = b"x" * 300
                self.assertEqual(self.session.handle(0, payload), kiss(0x90, b"\x02"))
                first = model.out.get_nowait()
                self.assertEqual(first[1:], payload[:254])
                self.assertTrue(model.out.empty())
                self.assertEqual((model.mode, model.mask, model.length), ("rx", 0x62, 255))
                model.frames.put((2, b"\x30incoming"))
                self.assertTrue(self.session.poll().endswith(kiss(0, b"incoming")))
                model.emit = model.out.put
                model.tx_result = 1
                self.assertEqual(self.session.handle(0, payload), kiss(0x0f, b"\x01"))
                retry, last = model.out.get_nowait(), model.out.get_nowait()
                self.assertNotEqual(first[0], retry[0])
                reassembly = Reassembly()
                for frame in (first, retry):
                    self.assertIsNone(reassembly.accept(frame))
                self.assertEqual(reassembly.accept(last), payload)

    def test_failed_rx_restore_propagates_and_cannot_report_ready(self):
        self.model.radio.on = Mock(side_effect=OSError("RX failed"))
        with self.assertRaisesRegex(OSError, "RX failed"):
            self.session.handle(0, b"message")

    def test_board_profile_rejects_tx_before_spi(self):
        model = Model(500_000)
        session = Session(model.radio)
        for cmd, value in PARAMS.items():
            session.handle(cmd, value)
        session.handle(6, b"\x01")
        count = len(model.ops)
        self.assertEqual(session.handle(0, b"message"), kiss(0x90, b"\x02"))
        self.assertEqual(count, len(model.ops))
        for opcode in (0x95, 0x8e, 0x0e, 0x83):
            self.assertNotIn(opcode, model.radio.COMMANDS)
        self.assertFalse(hasattr(Transceiver, "open"))


if __name__=="__main__":
    unittest.main()
