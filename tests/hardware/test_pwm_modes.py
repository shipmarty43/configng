import errno
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/armbian-config"))
from pwm_modes import Profile
from pwm_modes_live import fan_drive, operate


class Sysfs:
    def __init__(self, path, profile):
        self.root = path
        self.profile = profile
        platform = path / "device"
        platform.mkdir()
        self.params = platform / "header_pwm_profiles"
        self.params.write_text("\n".join(f"{n} {n^1 if profile.mode=='pair' else 255} "
            f"{profile.values[0] if profile.mode=='pair' else 0} "
            f"{profile.values[0] if profile.mode=='burst' else 0}" for n in profile.channels))
        (platform / "pulse_busy").touch()
        self.exported = set()
        self.writes = []
        self.busy = [0]
        self.sample = "100000 25000"
        self.fail = None

    def write(self, path, value):
        key = path.name
        if self.fail == key:
            raise OSError("injected failure")
        if key == "export":
            if value in self.exported:
                raise OSError(errno.EBUSY, "owned")
            self.exported.add(value)
        elif key == "unexport":
            self.exported.remove(value)
        self.writes.append((key, value))

    def read(self, path):
        if path == self.params:
            return path.read_text()
        if path.name == "capture":
            if isinstance(self.sample, Exception):
                raise self.sample
            return self.sample
        if path.name == "pulse_busy":
            return str(self.busy.pop(0) if len(self.busy)>1 else self.busy[0])
        return "0"

    def run(self, *args, now=lambda: 0):
        return operate(self.profile, self.root, args, write=self.write, read=self.read,
                       sleep=lambda _: None, now=now)


class TestLiveModes(unittest.TestCase):
    def fixture(self, mode, values=(), board="a733"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Sysfs(Path(tmp.name), Profile(board, mode, 2, values))

    def test_fan_drive_matches_board_device(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sensor = root / "class/hwmon/hwmon7"
            (sensor / "device").mkdir(parents=True)
            (sensor / "pwm1").write_text("128")
            self.assertIn("unavailable", fan_drive(root))
            of_node = root / "firmware/devicetree/base/soc@3000000/pwm-fan"
            of_node.mkdir(parents=True)
            (sensor / "device/of_node").symlink_to(of_node)
            self.assertEqual(fan_drive(root), "Requested drive 128/255 (50.2%)")
            (sensor / "fan1_input").write_text("2500")
            self.assertIn("Measured RPM: 2500", fan_drive(root))

    def test_capture_is_input_only(self):
        io = self.fixture("capture")
        self.assertIn("10000.00 Hz, 25.00%", io.run())
        self.assertEqual(io.writes, [("export",2), ("unexport",2)])
        for sample in ("0 0", "10 11", "invalid", TimeoutError()):
            io.sample = sample
            with self.assertRaises((ValueError, TimeoutError)):
                io.run()
            self.assertFalse(io.exported)

    def test_burst_waits_for_hardware(self):
        io = self.fixture("burst", (17,))
        io.busy = [4,4,0]
        self.assertIn("17 programmed periods", io.run(100000,25000))
        self.assertEqual(io.busy, [0])
        self.assertFalse(io.exported)
        self.assertEqual(io.writes[-3:], [("enable",0),("unexport",3),("unexport",2)])

    def test_timeout_aborts_and_releases(self):
        io = self.fixture("burst",(1,))
        io.busy = [4]
        with self.assertRaises(TimeoutError):
            io.run(100000,25000,now=iter([0,2]).__next__)
        self.assertFalse(io.exported)
        self.assertIn(("enable",0), io.writes)

    def test_pair_bounds_and_conflict(self):
        for board in ("a733", "h618"):
            io = self.fixture("pair",(500,),board)
            with self.assertRaises(ValueError):
                io.run(100000,500,10)
            self.assertEqual(io.writes, [])
            io.exported.add(3)
            with self.assertRaises(OSError):
                io.run(100000,25000,10)
            self.assertEqual(io.exported,{3})
            self.assertNotIn(("enable",1), io.writes)
            io.exported.clear()
            self.assertIn("500.00 ns",io.run(100000,25000,10))
            self.assertFalse(io.exported)

    def test_unknown_driver_and_ignored_dt_fail_before_export(self):
        io = self.fixture("burst",(17,))
        io.params.write_text("2 255 0 0")
        with self.assertRaises(ValueError):
            io.run(100000,25000)
        io.params.unlink()
        with self.assertRaises(ValueError):
            io.run(100000,25000)
        self.assertFalse(io.writes)

    def test_failure_before_start_releases_both_members(self):
        io = self.fixture("pair",(500,))
        io.fail = "period"
        with self.assertRaises(OSError):
            io.run(100000,25000,10)
        self.assertFalse(io.exported)
        self.assertNotIn(("enable",1),io.writes)


if __name__ == "__main__":
    unittest.main()
