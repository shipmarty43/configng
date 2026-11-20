"""Receive-only RNode single-radio host adapter for the Waveshare SX1262 HAT."""
import argparse
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import select
import signal
import socket
import stat
import sys
import time

import sx1262_profile as board
import sx1262_spi
from rnode_wire import Decoder, kiss
from rnode_metrics import Publisher, RxMetrics
from sx1262_rx import FREQUENCY, BANDWIDTH, SF, CR, PREAMBLE, Receiver

ADDRESS = ("127.0.0.1", 7633)
POLICY = Path("/etc/systemd/system/opi-reticulum-radio.service.d/50-devices.conf")
PARAMS = {1: FREQUENCY.to_bytes(4,"big"), 2: BANDWIDTH.to_bytes(4,"big"),
          3: bytes([0]), 4: bytes([SF]), 5: bytes([CR])}
ERROR = 0x90


class Session:
    def __init__(self, radio, metrics=None):
        self.radio = radio
        self.online = False
        self.configured = set()
        self.metrics = metrics if metrics is not None else RxMetrics()
        self.metrics.host = "connected / standby"

    def handle(self, cmd, data):
        if cmd == 8 and data == b"s":
            return kiss(8, b"F")
        if cmd in (0x50,0x48,0x49) and data == b"\x00":
            # Host protocol compatibility level; no ESP/nRF peripheral capabilities.
            return kiss(cmd, b"\x01\x34" if cmd == 0x50 else b"\x00")
        if cmd in PARAMS:
            expected = PARAMS[cmd]
            if data == expected:
                self.configured.add(cmd)
            elif data != (bytes(4) if cmd in (1,2) else b"\xff"):
                self.close()
                self.configured.discard(cmd)
                return kiss(ERROR, b"\x01")
            return kiss(cmd, expected)
        if cmd == 6 and data in (b"\x00", b"\x01", b"\xff"):
            if data == b"\x01" and not self.online:
                if self.configured != PARAMS.keys():
                    return kiss(ERROR,b"\x01")
                self.radio.on()
                self.online = True
                self.metrics.host = "connected / RX online"
            elif data == b"\x00":
                self.close()
            return kiss(cmd, bytes([self.online]))
        if cmd == 0x0a and data == b"\xff":
            self.close()
        if cmd == 0x0f:
            return kiss(cmd,b"\x01")
        if cmd == 0:
            if not self.online or not data:
                return kiss(ERROR,b"\x02")
            try:
                self.radio.send(data)
            except PermissionError:
                return kiss(ERROR,b"\x02")
            return kiss(0x0f,b"\x01")
        return b""

    def close(self):
        if self.online:
            self.radio.off()
        self.online = False
        self.metrics.host = "connected / standby"
        self.metrics.reassembly.discard()

    def poll(self):
        if self.online:
            now = time.monotonic()
            self.metrics.reassembly.expire(now)
            event = self.radio.read_event()
            if event is not None:
                return self.metrics.consume(event, now)
        return b""


def serve(radio, listener, stopping, publisher=None):
    metrics = RxMetrics()
    peer = session = None
    try:
        while not stopping():
            if publisher:
                publisher.update(metrics, time.monotonic())
            readable, _, _ = select.select([listener] + ([peer] if peer else []), [], [], .02 if peer else .25)
            if listener in readable:
                conn, _ = listener.accept()
                if peer:
                    conn.close()
                else:
                    peer = conn
                    peer.settimeout(.5)
                    session, decoder = Session(radio, metrics), Decoder()
            if not peer:
                continue
            try:
                if peer in readable:
                    block = peer.recv(2048)
                    if not block:
                        raise ConnectionError("Client disconnected")
                    for cmd, data in decoder.feed(block):
                        reply = session.handle(cmd, data)
                        if reply:
                            peer.sendall(reply)
                incoming = session.poll()
                if incoming:
                    peer.sendall(incoming)
            except (ConnectionError, socket.timeout):
                peer.close()
                peer = None
                session.close()
                metrics.host = "disconnected"
    finally:
        if peer:
            peer.close()
        if session:
            session.close()


def checked_route(live=False):
    route = board.discover()
    hz = sx1262_spi.selected(route.max_hz)
    from rnode_link import validate
    validate(Path("/etc/opi-mesh/reticulum.conf"))
    if live:
        board.require(board.PROFILE.is_file() and board.PROFILE.read_text().strip()=="hardware", "Hardware profile is not selected")
        board.require(POLICY.is_file() and POLICY.read_text()==board.device_policy(route),
                      "Reticulum device access is sealed")
    return route,hz


def start():
    route,hz = checked_route(True)
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with ExitStack() as stack:
        fd = os.open(board.LOCK,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        stack.callback(os.close,fd)
        info = os.fstat(fd)
        board.require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,"Invalid radio lock")
        fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        board.require(checked_route(True)==(route,hz),"SPI route changed")
        board.check_bindings(route)
        radio = Receiver.open(route, hz, stack)
        with socket.create_server(ADDRESS,backlog=1) as listener:
            endpoint = os.environ.get("NOTIFY_SOCKET")
            if endpoint:
                with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as notify:
                    notify.sendto(b"READY=1", endpoint.replace("@","\0",1) if endpoint.startswith("@") else endpoint)
            runtime = os.environ.get("RUNTIME_DIRECTORY")
            publisher = Publisher(runtime, hz) if runtime and os.environ.get("INVOCATION_ID") else None
            serve(radio, listener, lambda: stopped, publisher)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",choices=("check","preflight","start","device-policy"))
    action = cli.parse_args().action
    if action == "start":
        start()
        return
    route,hz = checked_route(action=="preflight")
    if action == "device-policy":
        print(board.device_policy(route),end="")
        return
    import gpiod
    board.require(hasattr(gpiod,"LineSettings"), "Requires libgpiod v2 Python bindings")
    print(f"RNode host interface (RX only): {route.spi}, SPI mode 0, 8 bits, MSB first, {hz} Hz; kernel CS0 on PI3.")
    print(f"LoRa: {FREQUENCY} Hz, BW {BANDWIDTH} Hz, SF{SF}, CR 4/{CR}, preamble {PREAMBLE}, sync 0x1424.")
    print("Device binding:", "present" if POLICY.is_file() and POLICY.read_text()==board.device_policy(route) else "sealed")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, ImportError) as error:
        sys.exit(str(error))
