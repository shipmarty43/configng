from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"share/armbian-config"))
import h616_uart as uart


class Profiles(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.node = self.root / "soc/serial@5000c00"
        self.node.mkdir(parents=True)
        self.group = self.node.parent / "pinctrl@300b000/test"
        self.group.mkdir(parents=True)
        handle = (17).to_bytes(4, "big")
        (self.group / "phandle").write_bytes(handle)
        (self.group / "function").write_bytes(b"uart3\0")
        (self.group / "pins").write_bytes(b"PI9\0PI10\0")
        (self.node / "pinctrl-0").write_bytes(handle)
        for key, value in (("BACKUPS", self.root/"run"), ("PROFILES", self.root/"etc")):
            mock = patch.object(uart, key, value)
            mock.start()
            self.addCleanup(mock.stop)

    def cli(self, *args):
        with patch.object(sys, "argv", ["uart", *args]):
            uart.main()

    def test_save_replace_renumber_and_forget(self):
        self.cli("save", "uart3", "9600", "8", "none", "1")
        self.cli("save", "uart3", "57600", "7", "even", "2")
        saved = (uart.PROFILES/"uart3.json").read_bytes()
        with self.assertRaises(ValueError):
            self.cli("save", "uart3", "57600", "7", "even", "1.5")
        self.assertEqual(saved, (uart.PROFILES/"uart3.json").read_bytes())
        with patch.object(uart, "ports", return_value={"ttyS7":self.node}), \
                patch.object(uart, "busy", return_value=""), patch.object(uart, "reserved", return_value=""), \
                patch.object(uart, "configure") as configure:
            self.cli("restore-profile", "ttyS7")
            configure.assert_called_once_with("ttyS7", self.node, "set", uart.framing(57600, 7, "even", "2"))
            self.cli("forget", "uart3")
            self.cli("restore-profile", "ttyS7")
            configure.assert_called_once()

    def test_refuse_wrong_route_and_owners(self):
        self.cli("save", "uart3", "9600", "8", "none", "1")
        with patch.object(uart, "ports", return_value={"ttyS2":self.node}), patch.object(uart, "configure") as configure:
            for busy, reserved in (("kernel console",""), ("open by PID 42",""), ("","serial getty configured")):
                with patch.object(uart,"busy",return_value=busy), patch.object(uart,"reserved",return_value=reserved):
                    self.cli("restore-profile","ttyS2")
            (self.group/"function").write_bytes(b"uart2\0")
            with self.assertRaisesRegex(ValueError,"header route"):
                self.cli("restore-profile","ttyS2")
            configure.assert_not_called()

    def test_idle_gnss_and_socket_activated_gpsd(self):
        gpsd, gnss = self.root/"gpsd", self.root/"gnss"
        alias = self.root/"receiver"
        alias.symlink_to("/dev/ttyS0")
        gpsd.write_text(f'DEVICES="{alias} /dev/ttyUSB0" # configured receiver\n')
        self.assertEqual(uart.reserved("ttyS0", gpsd, gnss), "configured gpsd receiver")
        gpsd.unlink()
        uart.save(gnss, {"mode":"auto", "device":str(alias)})
        self.assertEqual(uart.reserved("ttyS0", gpsd, gnss), "configured Waveshare GNSS receiver")


if __name__ == "__main__":
    unittest.main()
