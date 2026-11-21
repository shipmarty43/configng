from pathlib import Path
from tempfile import TemporaryDirectory
import os
import pty
import sys
import termios
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"share/armbian-config"))
import h616_uart as uart
import h616_pwm as pwm
import i2c_clocks as twi


class Controls(unittest.TestCase):
    def test_twi_dividers(self):
        for fin in (24_000_000, 100_000_000, 24_000_031):
            grid = twi.rates(fin)
            for hz, (m, n) in grid.items():
                self.assertEqual(fin // (10 * (m+1) * 2**n), hz)
                self.assertEqual(twi.choice(hz, grid), (hz, m, n))
            for bad in (0, min(grid)-1, 400001, "10k"):
                with self.assertRaises(ValueError):
                    twi.choice(bad, grid)
        grid = twi.rates(24_000_000)
        self.assertEqual((len(grid), min(grid), max(grid)), (67, 1171, 400000))
        self.assertEqual(twi.choice(250_000, grid), (240_000, 9, 0))
        self.assertEqual(twi.choice(400_000, grid), (400_000, 5, 0))

    def test_uart_route_through_serial_base(self):
        with TemporaryDirectory() as tmp:
            sysroot = Path(tmp)
            node = sysroot/"firmware/devicetree/base/soc/serial@5000400"
            node.mkdir(parents=True)
            (node.parent.parent/"compatible").write_bytes(b"xunlong,orangepi-zero2w\0")
            (node/"compatible").write_bytes(b"snps,dw-apb-uart\0")
            parent = sysroot/"devices/platform/soc/5000400.serial"
            child = parent/"serial-base/port"
            child.mkdir(parents=True)
            (parent/"driver").mkdir()
            (parent/"of_node").symlink_to(node)
            tty = sysroot/"class/tty/ttyS3"
            tty.mkdir(parents=True)
            (tty/"device").symlink_to(child)
            dev = sysroot/"dev"
            dev.mkdir()
            (dev/"ttyS3").symlink_to("/dev/null")
            self.assertEqual(uart.ports(sysroot, dev), {"ttyS3":node})
            (node/"status").write_bytes(b"disabled\0")
            self.assertEqual(uart.ports(sysroot, dev), {})

    def test_uart_framing(self):
        self.assertIn("7 bits, odd parity, 2 stop", uart.describe(uart.framing(115200, 7, "odd", "2")))
        self.assertIn("1.5 stop", uart.describe(uart.framing(9600, 5, "even", "1.5")))
        for args in ((0, 8, "none", "1"), (9600, 5, "none", "2"), (9600, 8, "x", "1")):
            with self.assertRaises(ValueError):
                uart.framing(*args)
        m, s = pty.openpty()
        try:
            original = uart.fields(termios.tcgetattr(s))
            target = uart.framing(57600, 8, "none", "1")
            self.assertEqual(uart.apply(s, target), original)
            self.assertEqual(uart.apply(s, original), target)
        finally:
            os.close(m)
            os.close(s)

    def test_uart_driver_roundtrip_required(self):
        # Represent a driver which silently substitutes 8N1 for 7E2.
        old = [0, 0, termios.CS8, 0, termios.B9600, termios.B9600, []]
        wanted = uart.framing(57600, 7, "even", "2")
        with patch.object(termios, "tcgetattr", return_value=old), patch.object(termios, "tcsetattr") as put:
            with self.assertRaisesRegex(ValueError, "did not accept"):
                uart.apply(3, wanted)
            self.assertEqual(put.call_count, 2)
            self.assertEqual(put.call_args.args, (3, termios.TCSANOW, old))

    def test_twi_input_clock_and_duplicate_selections(self):
        with TemporaryDirectory() as tmp:
            sysroot = Path(tmp)
            path = sysroot / "kernel/debug/clk/bus-i2c1/clk_rate"
            path.parent.mkdir(parents=True)
            path.write_text("100000000\n")
            self.assertEqual(twi.clock("twi1", sysroot), (100_000_000, "live bus-i2c1"))
            self.assertIn("example", twi.clock("s-twi0", sysroot)[1])
        for names in (["opi-twi-clock-twi1-100000", "opi-twi-clock-twi1-400000"],
                      ["opi-twi-clock-s-twi0-999999"], ["opi-twi-clock-twi9-100000"]):
            with self.assertRaises(ValueError):
                twi.selections(names)

    def test_pwm_bounds_and_cleanup(self):
        for duty, active in (("0", 0), ("37.5", 375000), ("100", 1000000)):
            self.assertEqual(pwm.waveform(pwm.settings(1000, duty, "normal")), (1000000, active))
            self.assertEqual(pwm.waveform(pwm.settings(1000, duty, "inversed")), (1000000, 1000000-active))
        for hz, duty, polarity in ((0,"10","normal"),(1000001,"1","normal"),(10,"-1","normal"),
                                   (10,"100.1","normal"),(10,"1","invalid")):
            with self.assertRaises(ValueError):
                pwm.settings(hz, duty, polarity)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"pwm1").mkdir()
            lease = root/"lease"
            pwm.save(lease, ["foreign", 0, 0])
            with patch.object(pwm, "put", side_effect=OSError("busy")) as put:
                with self.assertRaises(OSError):
                    pwm.run(root, pwm.settings(1,"50","normal"), lease, lambda: None, lambda: None)
                self.assertEqual(put.call_count, 1)
            pwm.cleanup(root, lease)
            self.assertFalse((root/"unexport").exists())


if __name__ == "__main__":
    unittest.main()
