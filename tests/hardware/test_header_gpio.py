from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"share/armbian-config"))
import header_gpio as gpio
import header_gpio_live as live


class Double:
    def __init__(self, lines):
        self.lines = lines
        self.flags = {}

    def info(self, offset):
        if not 0 <= offset < self.lines:
            raise AssertionError(f"Invalid line info offset {offset}")
        return self.flags.get(offset,0), "fixture", None


class LiveTests(unittest.TestCase):
    def test_controller_lookup_tracks_of_node_not_chip_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for minor, ctl in ((7,gpio.MAIN_3W),(0,gpio.STANDBY)):
                node = root/"firmware/devicetree/base"/ctl.path[1:]
                node.mkdir(parents=True)
                device = root/"devices/platform"/str(minor)
                device.mkdir(parents=True)
                (device/"of_node").symlink_to(node)
                self.assertEqual(live.controller_for("a733",device/f"gpiochip{minor}",root),ctl)
                self.assertIsNone(live.controller_for("h618", device,root))

    def test_bank_scope_and_overlapping_chip_offsets(self):
        main, standby = Double(352), Double(64)
        chips = {gpio.MAIN_3W:main, gpio.STANDBY:standby}
        profile = {3:gpio.Setting("up","20","122")}  # main PB3 offset 35
        standby.flags[35] = live.USED | live.RISING
        main.flags[2] = live.USED | live.FALLING  # PA, not PB
        live.check_changes("a733", {}, profile, chips)
        main.flags[39] = live.USED | live.FALLING
        with self.assertRaisesRegex(ValueError,"PB7"):
            live.check_changes("a733",{},profile,chips)
        with self.assertRaisesRegex(ValueError,"PB7"):
            live.check_changes("a733",profile,{},chips)  # removing the filter also changes PB
        live.check_changes("a733",{}, {3:gpio.Setting("down","default","default")}, chips)
        main.flags[35] = live.USED
        with self.assertRaisesRegex(ValueError,"PB3 is in use"):
            live.check_changes("a733",{},profile,chips)
        with self.assertRaisesRegex(ValueError,"Cannot verify"):
            live.check_changes("a733",{},profile,{gpio.STANDBY:standby})

    def test_missing_clocks_or_vector_layout_disables_bank_filter(self):
        c = gpio.MAIN_2W
        phandle = (7).to_bytes(4, "big")
        props = {"clock-names": b"apb\0hosc\0losc\0", "clocks": phandle * 3,
                 "interrupt-controller": b"", "#interrupt-cells": (3).to_bytes(4,"big"),
                 "interrupts": bytes(12 * len(c.irq_banks))}
        nodes = {c.path:props, "/clk":{"phandle":phandle, "#clock-cells":bytes(4)}}
        self.assertEqual(gpio.bank_vector(nodes,c),[0]*len(c.irq_banks))
        props["input-debounce"] = bytes(4)
        with self.assertRaisesRegex(ValueError,"array length"):
            gpio.bank_vector(nodes,c)
        props["clock-names"] = b"apb\0hosc\0"
        with self.assertRaisesRegex(ValueError,"clocks unavailable"):
            gpio.bank_vector(nodes,c)

    def test_read_only_v2_ioctl_layout(self):
        def ioctl(fd, op, data):
            self.assertEqual(fd,17)
            if op == live.CHIP_INFO:
                struct.pack_into("=I",data,64,288)
            else:
                self.assertEqual((op,len(data)), (live.LINE_INFO,256))
                self.assertEqual(struct.unpack_from("=I",data,64),(76,))
                data[32:37] = b"owner"
                struct.pack_into("=IQ", data,68,1,live.USED|live.RISING)
                struct.pack_into("=IIQ",data,80,3,0,250)
        chip=live.Chip(17,ioctl)
        self.assertEqual(chip.lines,288)
        self.assertEqual(chip.info(76),(live.USED|live.RISING,"owner",250))


if __name__ == "__main__":
    unittest.main()
