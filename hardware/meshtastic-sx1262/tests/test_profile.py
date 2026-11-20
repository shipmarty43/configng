import fcntl
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[3] / "share/armbian-config"))
import sx1262_spi
import sx1262_profile as p


def tree(root):
    dt = root/"firmware/devicetree/base"
    ctrl, pio = dt/"soc/spi@5011000", dt/"soc/pinctrl@300b000"
    radio, group = ctrl/"radio@0", pio/"spi1-pins"
    chip, spi = root/"bus/gpio/devices/gpiochip5", root/"class/spidev/spidev7.0"
    gpio_class = root/"class/gpio/chip5"
    for d in [radio, group, chip, spi/"device", gpio_class]:
        d.mkdir(parents=True)
    for path, data in {
        dt/"compatible": b"xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0",
        pio/"compatible": b"allwinner,sun50i-h616-pinctrl\0",
        pio/"phandle": p.cells(9), group/"phandle": p.cells(11),
        group/"function": b"spi1\0", group/"pins": b"PH6\0PH7\0PH8\0",
        ctrl/"num-cs": p.cells(1), ctrl/"cs-gpios": p.cells(9,8,3,1),
        ctrl/"pinctrl-0": p.cells(11), radio/"reg": p.cells(0),
        radio/"spi-max-frequency": p.cells(2000000), radio/"compatible": b"semtech,sx1262\0armbian,spi-dev\0",
        gpio_class/"ngpio": b"288\n", gpio_class/"label": b"300b000.pinctrl\n",
        chip/"dev": b"254:5\n", spi/"dev": b"153:1\n",
    }.items():
        path.write_bytes(data)
    (chip/"of_node").symlink_to(pio); (spi/"device/of_node").symlink_to(radio)
    return ctrl, pio


class Profile(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ctrl, self.pio = tree(self.root)
        setting = patch.object(sx1262_spi, "SETTING", self.root/"spi-hz")
        setting.start()
        self.addCleanup(setting.stop)

    def test_route_and_mapping_follow_renumbered_devices(self):
        import yaml
        route = p.discover(self.root)
        self.assertEqual(route, p.Route("spidev7.0", 5, "153:1", "254:5"))
        lora = yaml.safe_load(p.render(route))["Lora"]
        for key, pin, line in (("IRQ",36,76),("Busy",38,260),("Reset",12,257),("RXen",31,271)):
            self.assertEqual(lora[key], dict(pin=pin, gpiochip=5, line=line))
        self.assertNotIn("CS", lora)
        self.assertNotIn("SX126X_ANT_SW", lora)
        self.assertEqual(lora["spiSpeed"], 2000000)

    def test_selected_clock_and_lower_device_limit(self):
        import yaml
        (self.ctrl/"radio@0/spi-max-frequency").write_bytes(p.cells(1000000))
        route = p.discover(self.root)
        self.assertEqual(yaml.safe_load(p.render(route))["Lora"]["spiSpeed"], 1000000)
        sx1262_spi.SETTING.write_text("500000\n")
        self.assertEqual(yaml.safe_load(p.render(route))["Lora"]["spiSpeed"], 500000)
        sx1262_spi.SETTING.write_text("1500000\n")
        with self.assertRaises(ValueError):
            p.render(route)

    def test_reject_second_cs_owner_or_fixed_rf_switch(self):
        route = p.discover(self.root)
        original = p.TEMPLATE.read_text()
        path = self.root/"candidate"
        with patch.object(p, "TEMPLATE", path):
            for text in (original.replace("  IRQ:", "  CS: 259\n  IRQ:"),
                         original.replace("  RXen:", "  SX126X_ANT_SW:")):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, "YAML differs"): p.render(route)

    def test_reject_conflicting_routes(self):
        radio = self.ctrl/"radio@0"
        for path, value in [(self.ctrl/"cs-gpios",p.cells(9,7,9,1)), (radio/"spi-cpol",b""),
                            (radio/"status",b"disabled\0"), (radio/"spi-max-frequency",p.cells(0)),
                            (self.pio/"gpio-line-names",b"custom\0"),
                            (self.pio/"spi1-pins/pins",b"PH0\0PH1\0"),
                            (self.root/"class/gpio/chip5/ngpio",b"32")]:
            with self.subTest(path=path):
                old = path.read_bytes() if path.exists() else None
                path.write_bytes(value)
                with self.assertRaises(ValueError): p.discover(self.root)
                if old is None: path.unlink()
                else: path.write_bytes(old)
        (self.ctrl/"other@0").mkdir()
        (self.ctrl/"other@0/reg").write_bytes(p.cells(0))
        with self.assertRaisesRegex(ValueError, "Duplicate"): p.discover(self.root)

    def test_exact_activation_policy(self):
        route = p.discover(self.root)
        with patch.object(p, "PROFILE", self.root/"profile"), patch.object(p,"ACCESS",self.root/"drop-in"):
            p.PROFILE.write_text("no-radio")
            with self.assertRaisesRegex(ValueError,"not selected"): p.gate(route)
            p.PROFILE.write_text("hardware")
            with self.assertRaisesRegex(ValueError,"sealed"): p.gate(route)
            p.ACCESS.write_text(p.device_policy(route).replace("gpiochip5","gpiochip3"))
            with self.assertRaisesRegex(ValueError,"sealed"): p.gate(route)
            p.ACCESS.write_text(p.device_policy(route))
            p.gate(route)

    def test_regular_files_never_pass_live_device_check(self):
        route = p.discover(self.root)
        for name in ("spidev7.0","gpiochip5"): (self.root/name).touch()
        with self.assertRaisesRegex(ValueError,"Incorrect device"): p.check_bindings(route, self.root)

    @unittest.skipUnless(importlib.util.find_spec("meshtastic"), "requires pinned Meshtastic Python SDK")
    def test_preferences_reject_drift_or_boot_reset(self):
        from meshtastic.protobuf import config_pb2, localonly_pb2
        prefs = self.root/"prefs"
        prefs.mkdir()
        cfg = localonly_pb2.LocalConfig(version=24)
        cfg.device.role = config_pb2.Config.DeviceConfig.CLIENT_MUTE
        cfg.lora.region = config_pb2.Config.LoRaConfig.EU_433
        cfg.lora.use_preset = True
        cfg.lora.modem_preset = config_pb2.Config.LoRaConfig.LONG_FAST
        file = prefs/"config.proto"
        original = cfg.SerializeToString()
        file.write_bytes(original)
        p.preferences(self.root)
        for section, key, value in (("lora","tx_enabled",True), ("lora","region",0),
                                    ("device","role",0), ("lora","override_frequency",915.0),
                                    ("lora","channel_num",1), ("lora","use_preset",False)):
            with self.subTest(key=key):
                changed = localonly_pb2.LocalConfig.FromString(original)
                setattr(getattr(changed,section),key,value)
                file.write_bytes(changed.SerializeToString())
                with self.assertRaises(ValueError): p.preferences(self.root)
        file.write_bytes(original)
        (prefs/"db.proto").touch()
        with self.assertRaisesRegex(ValueError, "Legacy"): p.preferences(self.root)

    def test_lock_contention_and_same_pid_exec(self):
        lock = self.root/"radio.lock"; lock.touch()
        with lock.open() as owner, patch.object(p,"LOCK",lock), patch.object(p,"gate"), patch.object(p,"check"):
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): p.launch()
        marker = self.root/"exec-pid"
        with subprocess.Popen([sys.executable,__file__,"child",str(self.root)]) as child:
            try:
                import time
                end = time.monotonic()+5
                while not marker.exists() and child.poll() is None and time.monotonic()<end: time.sleep(.02)
                self.assertEqual(int(marker.read_text()), child.pid)
                with lock.open() as contender, self.assertRaises(BlockingIOError):
                    fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally: child.terminate()
        with lock.open() as contender: fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)


def lock_child(root):
    # Exercise the production launcher's lock inheritance using an inert executable.
    route = p.Route("spidev7.0",5,"153:1","254:5")
    exe = root/"standin"; exe.write_text('#!/bin/sh\necho "$$" > new-pid\nmv new-pid exec-pid\nexec sleep 20\n')
    exe.chmod(0o700)
    os.chdir(root)
    with patch.object(p,"check",return_value=route), patch.object(p,"gate"), patch.object(p,"check_bindings"), \
            patch.object(p,"LOCK",root/"radio.lock"), patch.object(p,"RUNTIME",root), patch.object(p,"BINARY",exe):
        p.launch()


if __name__ == "__main__":
    if len(sys.argv)==3 and sys.argv[1]=="child": lock_child(Path(sys.argv[2]))
    else: unittest.main()
