"""Exercise the native SX1262 backend on two regular files in a private /dev."""
import argparse
from contextlib import closing
import fcntl
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from meshtastic.protobuf import config_pb2
from sim_client import connect_simulator
import sx1262_profile as p


def fixture_nodes():
    route = p.check()
    fake_spi, fake_gpio = Path("/dev")/route.spi, Path(f"/dev/gpiochip{route.chip}")
    p.require({n for _, n in socket.if_nameindex()} == {"lo"}, "Expected isolated loopback")
    p.require(all(stat.S_ISREG(n.lstat().st_mode) for n in (fake_spi, fake_gpio)), "Expected regular-file doubles")
    for mask in ("gpiochip*", "spidev*", "i2c-*", "ttyS*", "ttyUSB*", "mem", "bus/usb"):
        p.require(all(n in (fake_spi, fake_gpio) for n in Path("/dev").glob(mask)), "Physical device visible")
    return route, fake_spi, fake_gpio


def worker(library, root):
    # Only ordinary files may stand in for device-number validation in this
    # private test mount. Use the production gate, flock and exec in this PID.
    route, spi, chip = fixture_nodes()
    p.RUNTIME, p.VFS, p.LOCK = root, root/"firmware", root/"test.lock"
    p.PROFILE, p.ACCESS = root/"test-profile", root/"test-devices.conf"
    p.PROFILE.write_text("hardware\n")
    p.ACCESS.write_text(p.device_policy(route))
    os.environ.update(LD_PRELOAD=str(library.resolve(strict=True)),
                      OPI_FIXTURE_SPI=str(spi), OPI_FIXTURE_GPIO=str(chip))
    with patch.object(p, "check_bindings", side_effect=lambda _: fixture_nodes()):
        p.launch()


def run(library):
    fixture_nodes()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        prefs = root/"firmware/prefs"
        prefs.mkdir(parents=True)
        (prefs/"config.proto").write_bytes((p.VFS/"prefs/config.proto").read_bytes())
        lock = root/"test.lock"
        lock.touch()
        log = root/"native.log"
        with log.open("wb") as out:
            proc = subprocess.Popen([sys.executable, __file__, str(library), "--worker", str(root)],
                                    cwd=root, stdout=out, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+30
            while proc.poll() is None and time.monotonic() < deadline:
                if "MOCK RX\n" in log.read_text(errors="replace"):
                    break
                time.sleep(0.2)
            trace = log.read_text(errors="replace")
            events = [s for s in trace.splitlines() if s.startswith("MOCK ")]
            p.require("MOCK RX" in events, f"Native RX not reached: exit={proc.poll()}, trace={events[-20:]}")
            p.require(Path(f"/proc/{proc.pid}/exe").samefile(p.BINARY), "Launcher did not exec firmware")
            inode = lock.stat()
            found = False
            for line in Path("/proc/locks").read_text().splitlines():
                fields = line.split()
                if fields[1:5] == ["FLOCK", "ADVISORY", "WRITE", str(proc.pid)]:
                    major, minor, number = fields[5].split(":")
                    found |= (int(major,16), int(minor,16), int(number)) == (
                        os.major(inode.st_dev), os.minor(inode.st_dev), inode.st_ino)
            p.require(found, "Native firmware did not retain its MainPID owner lock")
            p.ready()  # Exercise the service's ExecStartPost probe.
            (root/"mock-irq").touch()
            end = time.monotonic()+8
            while proc.poll() is None and time.monotonic() < end:
                trace = log.read_text(errors="replace")
                if "MOCK IRQ CLEAR" in trace and "MOCK RX" in trace.split("MOCK IRQ CLEAR", 1)[1]:
                    break
                time.sleep(0.1)
            p.require(all(flag in trace for flag in ("MOCK DIO1 HIGH","MOCK IRQ STATUS","MOCK IRQ CLEAR"))
                      and "MOCK RX" in trace.split("MOCK IRQ CLEAR", 1)[-1], "Synthetic RX IRQ recovery failed")
            with closing(connect_simulator(4403, 8)) as client:
                cfg = client.localNode.localConfig
                p.require(cfg.device.role == config_pb2.Config.DeviceConfig.CLIENT_MUTE and not cfg.lora.tx_enabled
                          and cfg.lora.region == config_pb2.Config.LoRaConfig.EU_433, "Unexpected native RF settings")
                # Negative test: only the fake radio exists and its TX opcodes unconditionally abort.
                packet = client.sendText("offline transmit-inhibit test", wantAck=False)
                end = time.monotonic()+10
                while time.monotonic() < end:
                    status = client.queueStatus
                    if status and status.mesh_packet_id == packet.id:
                        break
                    time.sleep(0.02)
                p.require(status and status.mesh_packet_id == packet.id and status.res == 34,
                          f"Expected correlated ERRNO_DISABLED (34), got {status}")
            trace = log.read_text(errors="replace")
            p.require(proc.poll() is None and "MOCK REJECT" not in trace, "Unexpected opcode or native exit")
            p.require(set(re.findall(r"^MOCK GPIO (\d+)$", trace, re.M)) == {"257","260","76","271"},
                      "Wrong GPIO claims")
            p.require("MOCK LEVEL 257 0" in trace and "MOCK LEVEL 257 1" in trace and "MOCK DIO2 SWITCH" in trace,
                      "Missing reset or internal RF switch")
            frequencies = [int(n) for n in re.findall(r"^MOCK RF HZ (\d+)$", trace, re.M)]
            p.require(frequencies and all(433050000 <= n <= 434790000 for n in frequencies), "Frequency outside EU_433")
            print(f"PASS: four GPIO offsets; reset pulse; SPI mode 0 at 2 MHz; DIO2 switch; RXen HIGH at SetRx; {frequencies[-1]} Hz")
            print("PASS: native firmware rejected the synthetic phone text before a TX opcode")
            print("PASS: synthetic DIO1/RX_DONE+CRC_ERR, IRQ read/clear and receive re-arm")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        with lock.open() as contender:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("PASS: launcher exec, MainPID flock, readiness and release after stop")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("library", type=Path)
    cli.add_argument("--worker", type=Path)
    args = cli.parse_args()
    if args.worker:
        worker(args.library, args.worker)
    else:
        run(args.library)
