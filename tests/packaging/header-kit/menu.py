"""Select and save a complementary PWM profile in the installed terminal UI."""
import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time

pid, fd = pty.fork()
if pid == 0:
    os.environ.update(TERM="xterm", LANG="C.UTF-8")
    fcntl.ioctl(0,termios.TIOCSWINSZ,struct.pack("HHHH",32,110,0,0))
    os.execlp("armbian-config-zero2w","armbian-config-zero2w","--cmd","PWM002")
try:
    for marker in (b"Save complementary pair",b"Header channel",b"Pair dead time",b"Backup:"):
        received=bytearray()
        until=time.monotonic()+120
        while marker not in received:
            if time.monotonic()>=until:
                raise RuntimeError(f"PWM002 did not render {marker!r}: {bytes(received[-1600:])!r}")
            if select.select([fd],[],[],1)[0]:
                received.extend(os.read(fd,8192))
        os.write(fd,b"\r")
    print("PWM002 real PTY: saved complementary pair, 500 ns",flush=True)
finally:
    os.close(fd)
    try: os.killpg(pid,signal.SIGTERM)
    except ProcessLookupError: pass
    os.waitpid(pid,0)
