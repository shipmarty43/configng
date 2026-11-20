"""Native radio ownership and DT route tests, no hardware access."""
import fcntl
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

binary = sys.argv[1]
with TemporaryDirectory() as directory:
    root = Path(directory)
    setting = root/'spi-hz'
    for limit, value, expected in (
            (16_000_000, None, 2_000_000), (800_000, None, 800_000), (2999, None, None),
            (16_000_000, '16000000', 16_000_000), (40_000_000, '16000001', None),
            (2_000_000, '500000', 500_000), (2_000_000, '3000', 3000),
            (2_000_000, '2999', None), (2_000_000, '16000000', None)):
        if value is None:
            setting.unlink(missing_ok=True)
        else:
            setting.write_text(value + '\n')
        proc = subprocess.run([binary, 'clock', str(limit), setting], capture_output=True)
        if expected is None:
            assert proc.returncode != 0
        else:
            assert proc.returncode == 0 and int(proc.stdout) == expected
    path = root/'radio.lock'
    path.touch()
    def lock_process():
        return subprocess.Popen([binary, 'lock', path], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for abrupt in (False, True):
        with lock_process() as child, path.open('rb') as contender:
            assert child.stdout.readline() == b'locked\n'
            try:
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError('acquired while native service holds radio')
            if abrupt:
                child.kill()
            else:
                child.stdin.write(b'\n')
                child.stdin.flush()
            child.wait(timeout=3)
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with lock_process() as blocked:
                assert blocked.wait(timeout=3) != 0
    ctrl = root/'spi@5011000'
    pio = root/'pinctrl@300b000'
    pins = pio/'spi1-pins'
    node = ctrl/'radio@0'
    pins.mkdir(parents=True)
    node.mkdir(parents=True)
    (pio/'phandle').write_bytes(struct.pack('>I',9))
    (pins/'phandle').write_bytes(struct.pack('>I',12))
    (ctrl/'pinctrl-0').write_bytes(struct.pack('>I',12))
    (pins/'pins').write_bytes(b'PH6\0PH7\0PH8\0')
    (pins/'function').write_bytes(b'spi1\0')
    (ctrl/'cs-gpios').write_bytes(struct.pack('>4I',9,8,3,1))
    (node/'reg').write_bytes(bytes(4))
    (node/'compatible').write_bytes(b'semtech,sx1262\0armbian,spi-dev\0')
    def route(valid):
        assert (subprocess.run([binary,'route',root,node]).returncode == 0) == valid
    route(True)
    peer = ctrl/'spidev@0'
    peer.mkdir()
    (peer/'reg').write_bytes(bytes(4))
    route(False)
    (peer/'status').write_bytes(b'disabled\0')
    route(True)
    (ctrl/'cs-gpios').write_bytes(struct.pack('>4I',9,8,3,0))
    route(False)
    soc = root/'firmware/devicetree/base/soc'
    soc.parent.mkdir(parents=True)
    soc.symlink_to(root)
    dev = root/'class/spidev/spidev7.0/device'
    dev.mkdir(parents=True)
    (dev/'of_node').symlink_to(node)
    assert subprocess.check_output([binary, 'discover', root]).strip() == b'/dev/spidev7.0'
    other = root/'class/spidev/spidev8.0'
    other.symlink_to(dev.parent)
    assert subprocess.run([binary, 'discover', root]).returncode != 0
