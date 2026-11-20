from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/"meshtastic-sx1262"),
              str(Path(__file__).resolve().parents[3]/"share/armbian-config")]
import sx1262_spi
from sx1262_rx import Spi
from rnode_wire import Decoder, Reassembly, kiss, split_frames
from rnode_adapter import Session, PARAMS


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


if __name__=="__main__":
    unittest.main()
