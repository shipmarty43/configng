"""Mirror the selected board DT route in a unit-private sysfs for the QEMU PCI UART."""
from pathlib import Path
import os
import sys
import termios

import h616_uart as uart
from uart_routes import PIO, address, read_tree

proof = Path("/var/lib/opi-package-proof/uart-test-sys")
node = address("uart3")
if sys.argv[1] == "fixture":
    tree = read_tree(Path(sys.argv[2]))
    for dtpath in ("/", node, PIO + "/opi-uart3-header-pins"):
        base = proof / "firmware/devicetree/base" / dtpath.lstrip("/")
        base.mkdir(parents=True, exist_ok=True)
        for key, raw in tree[dtpath].items():
            (base / key).write_bytes(raw)
    devpath = "devices/platform/soc/5000c00.serial"
    device = proof/devpath
    device.mkdir(parents=True)
    (device/"driver").mkdir()
    (device/"of_node").symlink_to("/sys/firmware/devicetree/base" + node)
    tty = proof/"class/tty/ttyS1"
    tty.mkdir(parents=True)
    (tty/"device").symlink_to("/sys/" + devpath)
else:
    fd = os.open("/dev/ttyS1", os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        state = uart.fields(termios.tcgetattr(fd))
        print("PCI 16550A readback:", uart.describe(state))
        assert state == uart.framing(57600, 7, "even", "2")
    finally:
        os.close(fd)
