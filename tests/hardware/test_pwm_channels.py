"""Per-channel profiles, Armbian clock pairs and live tty guards; no devices."""
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"share/armbian-config"))
import h616_pwm as pwm
import pwm_routes as route


class Channels(unittest.TestCase):
    def test_independent_saved_profiles_with_legacy_pwm1(self):
        with TemporaryDirectory() as tmp, patch.object(pwm, "PROFILE", Path(tmp)/"pwm1.json"):
            def cli(*args):
                with patch.object(sys, "argv", ["pwm", *args]), redirect_stdout(io.StringIO()):
                    pwm.main()
            cli("set", "1234", "26.25", "normal")
            for n in (2, 3, 4):
                cli("--channel", str(n), "set", str(n*2000), str(n*10), "inversed")
            cli("--channel", "3", "default")
            self.assertFalse((Path(tmp)/"pwm3.json").exists())
            for n, expected in ((1,1234), (2,4000), (4,8000)):
                self.assertEqual(pwm.load(Path(tmp)/f"pwm{n}.json")["hz"], expected)
            for bad in ("0","5"):
                with self.assertRaises(SystemExit), patch("sys.stderr", io.StringIO()):
                    cli("--channel", bad, "default")

    def test_shared_clock_boundary_and_stock_ethernet(self):
        for period, expected in ((500,(24000000,0)),(500_000_000,(24000000,0)),
                                 (1_000_000_000,(24000000,1)),(200,(100000000,0)),(10,None)):
            self.assertEqual(pwm.pair_clock(period), expected)
        with TemporaryDirectory() as tmp:
            base = Path(tmp)/"base"; ctrl=base/route.CTRL.lstrip("/")
            ctrl.mkdir(parents=True)
            chip = Path(tmp)/"chip"; (chip/"device").mkdir(parents=True)
            (chip/"device/of_node").symlink_to(ctrl)
            def cells(*fields):
                return b"".join(n.to_bytes(4,"big") for n in fields)
            (ctrl/"phandle").write_bytes(cells(23)); (ctrl/"#pwm-cells").write_bytes(cells(3))
            eth=base/"ac300-clk"; eth.mkdir()
            (eth/"pwms").write_bytes(cells(23,5,500,0)); (eth/"compatible").write_bytes(b"pwm-clock\0")
            pwm.check_pair(chip, 4, 1_000_000)
            with self.assertRaisesRegex(ValueError,"PWM5"):
                pwm.check_pair(chip, 4, 1_000_000_000)
            (eth/"status").write_bytes(b"disabled\0")
            pwm.check_pair(chip, 4, 1_000_000_000)

    def test_live_uart0_cannot_be_silently_released(self):
        import h616_uart
        for reason in ("kernel console", "open by PID 20"):
            with patch.object(h616_uart,"ports",return_value={}), patch.object(h616_uart,"busy",return_value=reason):
                with self.assertRaisesRegex(ValueError,reason):
                    route.release_live_check()
        with patch.object(h616_uart,"ports",return_value={}), patch.object(h616_uart,"busy",return_value=""), \
                patch.object(h616_uart,"reserved",return_value="configured gpsd receiver"):
            with self.assertRaisesRegex(ValueError,"gpsd"):
                route.release_live_check()

if __name__ == "__main__":
    unittest.main()
