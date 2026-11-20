"""Run with python3 tests/hardware/test_console_tty.py. Uses a scratch boot directory."""
import os
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/armbian-config"))
import console_tty as console

SCRIPT = '''setenv console "both"
load ${devtype} ${devnum} ${load_addr} ${prefix}armbianEnv.txt
env import -t ${load_addr} ${filesize}
if test "${console}" = "display" || test "${console}" = "both"; then setenv consoleargs "console=ttyS0,115200 console=tty1"; fi
if test "${console}" = "serial"; then setenv consoleargs "console=ttyS0,115200"; fi
setenv bootargs "root=${rootdev} ${consoleargs}"
'''
ORIGINAL = "# SD\nconsole=both\noverlays=pwm1-pi11 i2c1-pi\nuser_overlays=zero2w-dfr0528 opi-zero2w-sx1262\n"


def image(script):
    data = script.encode()
    body = struct.pack(">II", len(data), 0) + data
    header = bytearray(64)
    header[:4] = bytes.fromhex("27051956")
    header[30] = 6
    struct.pack_into(">I", header, 12, len(body))
    struct.pack_into(">I", header, 24, zlib.crc32(body))
    struct.pack_into(">I", header, 4, zlib.crc32(header))
    return header + body


class Console(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.boot = Path(directory.name)
        (self.boot / "boot.scr").write_bytes(image(SCRIPT))
        self.env = self.boot / console.ENVFILE
        self.env.write_text(ORIGINAL)
        os.chmod(self.env, 0o640)
        targets = patch.object(console, "devices", return_value={"tty1": "", "tty3": "", "ttyS0": "", "ttyS5": ""})
        targets.start()
        self.addCleanup(targets.stop)

    def apply(self, target):
        console.change(self.boot, "set", target)

    def backups(self):
        return sorted((self.boot / "armbianEnv.txt.tty-backups").glob("change.*"))

    def test_actual_display_rule_and_switch(self):
        rules = console.supported_boot(self.boot)
        self.assertEqual(console.selection({"console":"display"}, rules)[0], ["ttyS0", "tty1"])
        self.apply("tty1")
        self.apply("tty1")
        self.assertEqual(len(self.backups()), 1)
        self.assertIn("consoleargs=console=tty1 systemd.mask=serial-getty@ttyS0.service\n", self.env.read_text())
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o640)
        console.change(self.boot, "rollback", self.backups()[0].name)
        self.assertEqual(self.env.read_text(), ORIGINAL)

    def test_rollback_preserves_independent_change(self):
        self.apply("tty3")
        backup, = self.backups()
        with self.env.open("a") as f:
            f.write("verbosity=4\n")
        console.change(self.boot, "rollback", backup.name)
        self.assertEqual(self.env.read_text(), ORIGINAL + "verbosity=4\n")

    def test_rollback_rejects_changed_target_and_bad_id(self):
        self.apply("tty1")
        backup, = self.backups()
        self.apply("tty3")
        expected = self.env.read_bytes()
        for name in (backup.name, "../boot.scr"):
            with self.assertRaises(ValueError):
                console.change(self.boot, "rollback", name)
        self.assertEqual(self.env.read_bytes(), expected)

    def test_dual_console_and_release_when_switching_back(self):
        with patch.object(console, "serial_users", return_value=[]):
            self.apply("ttyS5+tty1")
            self.assertIn("console=ttyS5,115200 console=tty1 systemd.mask=serial-getty@ttyS0.service", self.env.read_text())
            self.apply("ttyS0")
            self.assertIn("consoleargs=console=ttyS0,115200 systemd.mask=serial-getty@ttyS5.service", self.env.read_text())

    def test_conflicts_leave_environment_untouched(self):
        for extra in ("console=serial\n", "extraargs=console=tty0\n", "extraboardargs=earlycon\n"):
            self.env.write_text(ORIGINAL + extra)
            with self.assertRaises(ValueError):
                self.apply("tty1")
            self.assertEqual(self.env.read_text(), ORIGINAL + extra)
        self.env.write_text(ORIGINAL)
        for target in ("ttyS4", "tty1+tty1", "../tty1"):
            with self.assertRaises(ValueError):
                self.apply(target)
        with patch.object(console, "serial_users", return_value=["42"]), self.assertRaises(ValueError):
            self.apply("ttyS5")
        self.assertEqual(self.env.read_text(), ORIGINAL)

    def test_unrecognized_boot_route(self):
        for raw in (b"bad", image(SCRIPT + 'setenv consoleargs "console=bad"\n'),
                    image(SCRIPT.replace("env import -t", "# env import -t"))):
            (self.boot / "boot.scr").write_bytes(raw)
            with self.assertRaises(ValueError):
                self.apply("tty1")
        self.assertEqual(self.env.read_text(), ORIGINAL)

    def test_missing_console_key_restored(self):
        before = ORIGINAL.replace("console=both\n", "")
        self.env.write_text(before)
        self.apply("tty1")
        console.change(self.boot, "rollback", self.backups()[0].name)
        self.assertEqual(self.env.read_text(), before)


if __name__ == "__main__":
    unittest.main()
