"""Read GPIO v2 line information without requesting a line or generating edges."""
import argparse
import errno
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import stat
import struct
import sys

from header_gpio import CONTROLLERS, PADS, location, saved

# linux/gpio.h: chip_info, gpio_v2_line_info; fixed-layout UAPI on both ARM64 boards.
CHIP_INFO = 0x8044B401
LINE_INFO = 0xC100B405
USED, INPUT, RISING, FALLING = 1, 4, 16, 32


class Chip:
    def __init__(self, fd, ioctl=fcntl.ioctl):
        self.fd, self.ioctl = fd, ioctl
        data = bytearray(68)
        ioctl(fd, CHIP_INFO, data)
        self.lines, = struct.unpack_from("=I", data, 64)

    def info(self, offset):
        if not 0 <= offset < self.lines:
            raise ValueError(f"Line {offset} is outside this gpiochip")
        data = bytearray(256)
        struct.pack_into("=I", data, 64, offset)
        self.ioctl(self.fd, LINE_INFO, data)
        consumer = bytes(data[32:64]).split(b"\0",1)[0].decode(errors="replace")
        consumer = "".join(c if c.isprintable() else " " for c in consumer)
        flags, = struct.unpack_from("=Q", data, 72)
        count, = struct.unpack_from("=I", data, 68)
        if count > 10:
            raise ValueError("Invalid GPIO v2 attribute count")
        debounce = None
        for i in range(count):
            attribute, = struct.unpack_from("=I", data, 80 + 16*i)
            if attribute == 3:
                debounce, = struct.unpack_from("=I", data, 88 + 16*i)
        return flags, consumer, debounce


def controller_for(board, actual, sysroot):
    base = sysroot/"firmware/devicetree/base"
    paths = {(base/c.path.lstrip("/")).resolve(): c for c in CONTROLLERS[board]}
    for parent in (actual, *actual.parents):
        if not parent.is_relative_to((sysroot/"devices").resolve()):
            break
        ctl = paths.get((parent/"of_node").resolve())
        if ctl:
            return ctl
    return None


def discover(board, stack, sysroot=Path("/sys"), dev=Path("/dev")):
    chips = {}
    for device in dev.glob("gpiochip[0-9]*"):
        desc = device.stat()
        if not stat.S_ISCHR(desc.st_mode):
            continue
        name = f"{os.major(desc.st_rdev)}:{os.minor(desc.st_rdev)}"
        actual = (sysroot/"dev/char"/name).resolve()
        ctl = controller_for(board, actual, sysroot)
        if ctl is None:
            continue
        if ctl in chips:
            raise ValueError(f"Multiple gpiochips for {ctl.path}")
        fd = os.open(device, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        if os.fstat(fd).st_rdev != desc.st_rdev:
            raise ValueError(f"GPIO device changed while opening {device}")
        chips[ctl] = Chip(fd)
    return chips


def check_changes(board, old, new, chips):
    def periods(settings):
        values = {}
        for pin, setting in settings.items():
            if setting.debounce != "default":
                _, ctl, bank, _ = location(board,pin)
                values[ctl, bank] = int(setting.debounce)
        return values

    for pin, setting in new.items():
        if old.get(pin) == setting:
            continue
        pad, ctl, bank, line = location(board,pin)
        if ctl not in chips:
            raise ValueError(f"Cannot verify live ownership on {ctl.path}")
        flags, consumer, _ = chips[ctl].info(bank * 32 + line)
        if flags & USED:
            raise ValueError(f"{pad} is in use: {consumer or 'unnamed GPIO consumer'}")
    previous, candidate = periods(old), periods(new)
    for ctl, bank in previous.keys() | candidate.keys():
        if previous.get((ctl, bank)) == candidate.get((ctl, bank)):
            continue
        if ctl not in chips:
            raise ValueError(f"Cannot verify live IRQ consumers on {ctl.path}")
        chip = chips[ctl]
        if bank * 32 >= chip.lines:
            raise ValueError(f"Bank index {bank} is outside {ctl.path}")
        for offset in range(bank * 32, min((bank+1) * 32, chip.lines)):
            try:
                flags, consumer, _ = chip.info(offset)
            except OSError as exc:
                # Some sunxi bank tails have unimplemented offsets.
                if exc.errno == errno.EINVAL:
                    continue
                raise
            if flags & (RISING | FALLING):
                pad = f"P{chr(ord(ctl.origin)+bank)}{offset%32}"
                raise ValueError(f"Bank filter also affects live edges on {pad}: {consumer}")


def boot_preset(pin, sysroot=Path("/sys")):
    name = f"opi-header-gpio-{pin}"
    node = sysroot/"firmware/devicetree/base"/name
    if not node.is_dir():
        return "no pad preset"
    binding = sysroot/"bus/platform/devices"/name/"driver"
    status = "applied at probe" if binding.resolve().name == "opi-header-gpio" else "unbound"
    drive = (node/"drive-strength").read_bytes() if (node/"drive-strength").exists() else None
    bias = next((label for label, prop in (("up","bias-pull-up"),("down","bias-pull-down"),("off","bias-disable"))
                 if (node/prop).exists()), "default")
    return f"boot {status}: {bias}/{int.from_bytes(drive, 'big') if drive else 'default'}"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("board",choices=PADS)
    cli.add_argument("action",choices=("status","check"))
    cli.add_argument("args",nargs="*")
    a = cli.parse_args()
    with ExitStack() as stack:
        chips = discover(a.board, stack)
        if a.action == "check":
            before, after, folder = map(Path,a.args)
            check_changes(a.board,saved(before.read_text(),folder),saved(after.read_text(),folder),chips)
        else:
            for pin in PADS[a.board]:
                pad,ctl,bank,line=location(a.board,pin)
                if ctl not in chips:
                    print(f"{pin:2} {pad:5} {ctl.symbol}: gpiochip unavailable")
                    continue
                flags,owner,period=chips[ctl].info(bank*32+line)
                direction = "input" if flags & INPUT else "output" if flags & 8 else "unset"
                bias = next((name for bit,name in ((256,"up"),(512,"down"),(1024,"off")) if flags & bit), "unspecified")
                edge = "both" if flags & RISING and flags & FALLING else "rising" if flags & RISING else "falling" if flags & FALLING else "none"
                print(f"{pin:2} {pad:5} {ctl.symbol}:{bank*32+line:<3} "
                      f"{owner or ('claimed' if flags & USED else 'free')}  {direction} bias={bias} edge={edge} v2-debounce-us={period or 0}  {boot_preset(pin)}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError,OSError,KeyError) as exc:
        sys.exit(str(exc))
