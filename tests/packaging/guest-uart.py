"""Use the disconnected second QEMU 16550 to verify the installed UART backend."""
from pathlib import Path
import os
import sys
import termios
from unittest.mock import patch

import h616_uart as uart

name = "ttyS1"
device = Path("/dev")/name
assert device.is_char_device()
assert Path("/sys/class/net").is_dir() and {p.name for p in Path("/sys/class/net").iterdir()} == {"lo"}
assert name not in Path("/proc/consoles").read_text().split()
# Discovery on Zero 2W uses the physical DT route. Only substitute discovery:
# ownership, ioctls, termios, readback, file backup and rollback stay real.
def call(*args):
    with patch.object(sys, "argv", ["uart", *args]), patch.object(uart, "ports", return_value={name: Path("/soc/serial@5000400")}):
        uart.main()
def read():
    fd = os.open(device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        return uart.fields(termios.tcgetattr(fd))
    finally:
        os.close(fd)
old = read()
call("set", name, "57600", "7", "even", "2")
assert read() == uart.framing(57600, 7, "even", "2")
fd = os.open(device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
try:
    try:
        call("set", name, "9600", "8", "none", "1")
    except ValueError as e:
        assert "open by PID" in str(e)
    else:
        raise AssertionError("busy UART settings changed")
finally:
    os.close(fd)
call("rollback", name)
assert read() == old
print("PASS disconnected 16550: 57600 7E2, busy holder and exact runtime rollback")
