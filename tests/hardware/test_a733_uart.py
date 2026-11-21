import os
from pathlib import Path
import sys
import tempfile
import termios
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"share/armbian-config"))
import a733_uart as uart


class HeaderUART(unittest.TestCase):
    def test_identity_mux_and_framing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root/"firmware/devicetree/base"
            name = "ttyS17"
            port = "uart7"
            addr, function, pins, _ = uart.PORTS[port]
            node = base/(uart.SOC+addr).lstrip("/")
            node.mkdir(parents=True)
            (base/"compatible").write_bytes(b"xunlong,orangepi-zero3w\0arm,sun60iw2p1\0")
            binding = root/"devices/platform/uart"
            binding.mkdir(parents=True)
            (binding/"driver").mkdir()
            (binding/"of_node").symlink_to(node)
            tty = root/"class/tty"/name
            tty.mkdir(parents=True)
            (tty/"device").symlink_to(binding)
            (node/"compatible").write_bytes(b"allwinner,uart-v100\0")
            (node/"pinctrl-0").write_bytes(bytes([0,0,0,68]))
            group = base/uart.R_PIO.lstrip("/")/"uart7_pins@0"
            group.mkdir(parents=True)
            (group/"phandle").write_bytes((node/"pinctrl-0").read_bytes())
            (group/"function").write_bytes(function.encode()+b"\0")
            (group/"pins").write_bytes(b"PL2\0PL3\0")
            self.assertEqual(uart.identify(name, root), (port,node))
            with patch.object(uart,"PROFILES",root/"profiles"), patch.object(uart.serial,"BACKUPS",root/"locks"), patch.object(uart,"identify",return_value=(port,node)), patch.object(uart.serial,"busy",return_value=""), patch.object(uart.serial,"reserved",return_value="") as reserved, patch.object(uart.serial,"configure") as apply:
                uart.save(uart.PROFILES/"uart7.json",uart.serial.profile_record(port,57600,8,"none","1"))
                uart.restore(name)
                apply.assert_called_once_with(name,node,"set",uart.serial.framing(57600,8,"none","1"),label="UART7")
                reserved.return_value="serial getty configured"
                uart.restore(name)
                self.assertEqual(apply.call_count,1)
            (group/"pins").write_bytes(b"PL8\0PL9\0")
            self.assertIsNone(uart.identify(name, root))
            (base/"compatible").write_bytes(b"xunlong,orangepi-4-pro\0arm,sun60iw2p1\0")
            self.assertIsNone(uart.identify(name, root))
        master, slave = os.openpty()
        try:
            target = uart.serial.framing(57600,8,"none","1")
            uart.serial.apply(slave,target)
            self.assertEqual(uart.serial.fields(termios.tcgetattr(slave)),target)
        finally:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
