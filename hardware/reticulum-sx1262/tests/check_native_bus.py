"""Exercise the ARM64 Linux ioctl and libgpiod ABI with file-backed fixtures."""
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import socket
import subprocess
import sys
import stat
import tempfile

import rnode_adapter as adapter
import sx1262_profile as board
from rnode_adapter import Session, checked_route
from rnode_wire import Decoder, kiss
from rnode_metrics import RxMetrics
from sx1262_rx import Receiver

route,hz=checked_route()
assert {name for _,name in socket.if_nameindex()}=={"lo"}
for name in (route.spi, f"gpiochip{route.chip}"):
    assert stat.S_ISREG((Path("/dev")/name).lstat().st_mode)
assert os.environ["LD_PRELOAD"] and int(os.environ["OPI_FIXTURE_HZ"])==hz
if len(sys.argv)>1:
    from unittest.mock import patch
    root=Path(sys.argv[1])
    board.PROFILE=root/"test-profile"
    board.LOCK=root/"owner.lock"
    adapter.POLICY=root/"test-devices.conf"
    # Only device type qualification is replaced: both fixture nodes above
    # must be regular files; real sysfs discovery, gate, lock and serve run.
    with patch.object(board,"check_bindings",side_effect=lambda r: None if r==route else sys.exit(1)):
        adapter.start()
    sys.exit(0)


def lifecycle(root):
    lock=root/"owner.lock"
    lock.touch(); (root/"test-profile").write_text("hardware\n")
    (root/"test-devices.conf").write_text(board.device_policy(route))
    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as notify:
        endpoint=str(root/"notify")
        notify.bind(endpoint); notify.settimeout(7)
        worker=subprocess.Popen([sys.executable,__file__,str(root)],env=dict(os.environ,NOTIFY_SOCKET=endpoint,RUNTIME_DIRECTORY=str(root)),cwd=root)
        try:
            assert notify.recv(128)==b"READY=1"
            with lock.open() as contender:
                try: fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: pass
                else: raise AssertionError("Missing owner lock")
            inode=lock.stat()
            records=[line.split() for line in Path("/proc/locks").read_text().splitlines()]
            assert any(f[1:5]==["FLOCK","ADVISORY","WRITE",str(worker.pid)]
                       and tuple(int(v,base) for v,base in zip(f[5].split(":"),(16,16,10)))==
                       (os.major(inode.st_dev),os.minor(inode.st_dev),inode.st_ino) for f in records)
            with socket.create_connection(adapter.ADDRESS,timeout=2) as client:
                client.sendall(kiss(8,b"s"))
                assert client.recv(4,socket.MSG_WAITALL)==kiss(8,b"F")
        finally:
            worker.terminate(); worker.wait(timeout=4)
    assert worker.returncode==0
    with lock.open() as contender: fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
    print("PASS: full worker, readiness notification, MainPID flock, loopback detection and release")

with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
    previous=Path.cwd()
    os.chdir(tmp)
    stack.callback(os.chdir,previous)
    radio=Receiver.open(route,hz,stack)
    radio.on()
    Path("mock-irq").touch()
    metrics = RxMetrics()
    rejected = radio.read_event()
    assert rejected.irq == 0x42 and metrics.consume(rejected, 1) == b"" and metrics.crc == 1
    assert metrics.last is None and not Path("mock-irq").exists()
    Path("mock-good").touch()
    good = radio.read_event()
    assert good.rssi_dbm == -103.5 and good.snr_quarters == -29
    assert list(Decoder().feed(metrics.consume(good, 2))) == [(0x23,b"\x36"),(0x24,b"\xe3"),(0,b"AB")]
    assert not Path("mock-good").exists()
    print("PASS: native GetPacketStatus (207, 227, 80) -> -103.5 dBm, -7.25 dB; KISS precedes DATA")
    assert radio.poll() is None
    s=Session(radio); s.online=True
    assert s.handle(0,b"negative TX test")==kiss(0x90,b"\x02")
    print(f"PASS: real ARM64 ioctl/gpiod paths on ordinary files, {hz} Hz, mode 0, 8-bit MSB-first; reset, RXen, CRC discard, re-arm and TX refusal")

with tempfile.TemporaryDirectory() as tmp:
    lifecycle(Path(tmp))
