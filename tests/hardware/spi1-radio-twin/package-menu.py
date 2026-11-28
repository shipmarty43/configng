"""Select the shared route through the extracted package's real dialog on a scratch boot tree."""
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

deb, dt = (Path(x).resolve() for x in sys.argv[1:])
with tempfile.TemporaryDirectory() as tmp:
    w=Path(tmp)
    subprocess.run(["dpkg-deb","-x",deb,w/"pkg"],check=True)
    prefix=w/"pkg/opt/armbian-config-zero2w"
    boot=w/"boot"; (boot/"dtb").mkdir(parents=True); (boot/"dtb/allwinner").symlink_to(dt)
    (boot/"boot.scr").write_text("armbianEnv.txt overlay-user/${overlay_file}.dtbo")
    (boot/"armbianEnv.txt").write_text("overlay_prefix=sun50i-h616\n")
    (w/"live").mkdir(); (w/"live/compatible").write_bytes(b"xunlong,orangepi-zero2w\0allwinner,sun50i-h618\0")
    harness = '''
set -e
script_dir=$1/bin
declare -A module_options
source "$1/lib/armbian-config/config.functions.sh"
source "$1/lib/armbian-config/config.system.sh"
_ups_dfr_boot() { echo "$TEST_DIR/boot"; }
_ups_dfr_dt() { echo "$TEST_DIR/live"; }
DIALOG=dialog BACKTITLE="Zero 2W test"
module_sx1262_overlay select
'''
    pid,fd=pty.fork()
    if pid==0:
        fcntl.ioctl(0,termios.TIOCSWINSZ,struct.pack("HHHH",32,110,0,0))
        os.environ.update(TEST_DIR=str(w), LANG="C", TERM="xterm")
        os.execlp("bash","bash","-c",harness,"bash",str(prefix))
    try:
        for marker,keys in ((b"CS pins 40/26/24",b"\x1bOB\x1bOB\r"),(b"Backup:",b"\r")):
            data=bytearray(); end=time.monotonic()+12
            while marker not in data:
                if time.monotonic()>=end: raise RuntimeError(bytes(data[-900:]))
                if select.select([fd],[],[],0.2)[0]:
                    try: data.extend(os.read(fd,8192))
                    except OSError as exc: raise RuntimeError(bytes(data[-1200:])) from exc
            os.write(fd,keys)
        while os.waitpid(pid,os.WNOHANG)[0]==0:
            if time.monotonic()>end: raise TimeoutError("Dialog did not close")
            time.sleep(0.03)
        pid=None
        assert "user_overlays=opi-zero2w-spi1-radios" in (boot/"armbianEnv.txt").read_text()
        assert (boot/"overlay-user/opi-zero2w-spi1-radios.dtbo").is_file()
    finally:
        if pid is not None:
            try: os.killpg(pid,signal.SIGTERM)
            except ProcessLookupError: pass
            os.waitpid(pid,0)
        os.close(fd)
print("PASS packaged dialog installed the three-CS overlay in a disposable boot tree")
