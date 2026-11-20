"""Verify that a packaged --cmd entry opens a real dialog in a serial-only guest."""
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

item, expected = sys.argv[1:]
pid, tty = pty.fork()
if pid == 0:
    fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    os.environ.update(TERM="xterm", LANG="C.UTF-8")
    os.execlp("armbian-config-zero2w", "armbian-config-zero2w", "--cmd", item)
output = bytearray()
end = time.monotonic() + 90
try:
    while time.monotonic()<end:
        if select.select([tty], [], [], 0.5)[0]:
            try:
                data = os.read(tty, 8192)
            except OSError:
                break
            if not data:
                break
            output.extend(data)
            if expected.encode() in output:
                print("TUI-PASS", item, expected, flush=True)
                break
    if expected.encode() not in output:
        raise RuntimeError(f"{item} did not render: {bytes(output[-500:])!r}")
finally:
    os.close(tty)
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)
