"""Feed the same real, composed DTB to the GUI, mesh and C++ SX1262 route checks."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parents[3]
dt, gui, native = map(Path, sys.argv[1:])
sys.path[:0] = [str(here/"share/armbian-config"),str(gui)]
from uart_routes import read_tree
from core.sx1262_spi import find_spi
from sx1262_spi import discover

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); dtroot = root/"firmware/devicetree/base"; soc = dtroot/"soc"
    ctrl = soc/"spi@5011000"; pio = soc/"pinctrl@300b000"
    for path, data in read_tree(dt).items():
        dest = dtroot/path.strip("/")
        if dest not in (dtroot, soc, ctrl, pio, pio/"spi1-pins") and dest.parent != ctrl:
            continue
        dest.mkdir(parents=True,exist_ok=True)
        for key,val in data.items(): (dest/key).write_bytes(val)
    for cs,name in enumerate(("radio@0","cc1101@1","nrf24@2")):
        d=root/f"class/spidev/spidev7.{cs}"; (d/"device").mkdir(parents=True)
        (d/"device/of_node").symlink_to(ctrl/name); (d/"dev").write_text(f"153:{cs}")
    chip=root/"bus/gpio/devices/gpiochip5"; chip.mkdir(parents=True)
    (chip/"of_node").symlink_to(pio); (chip/"dev").write_text("254:5")
    c=root/"class/gpio/chip5"; c.mkdir(parents=True)
    (c/"label").write_text("300b000.pinctrl"); (c/"ngpio").write_text("288")
    def checks(ok):
        for fn in (lambda: find_spi("auto",0,sysfs=root),lambda:discover(root)):
            try: fn()
            except (ValueError,OSError): assert not ok
            else: assert ok
        code=subprocess.run([native,"route",soc,ctrl/"radio@0"],capture_output=True).returncode
        assert (code == 0) == ok
    checks(True)
    for path, bad in ((ctrl/"cs-gpios",(ctrl/"cs-gpios").read_bytes()[:-16]),
                      (ctrl/"nrf24@2/reg",struct.pack(">I",1)),
                      (ctrl/"nrf24@2/ce-gpios",bytes(16)),(ctrl/"radio@0/reset-gpios",bytes(16)),
                      (ctrl/"cc1101@1/spi-cpha",b"")):
        old=path.read_bytes() if path.exists() else None
        path.write_bytes(bad); checks(False)
        if old is None: path.unlink()
        else: path.write_bytes(old)
    checks(True)
print("PASS shared route and five malformed layouts across GUI, mesh and LoRaWAN consumers")
