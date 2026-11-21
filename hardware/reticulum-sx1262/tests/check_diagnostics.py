"""Run as a disposable no-radio worker inside the test lock and device sandbox."""
import argparse
import json
import os
from pathlib import Path
import queue
import signal
import socket
import tempfile
import threading
import time

import RNS
from RNS.Interfaces.RNodeInterface import RNodeInterface
from RNS.vendor.configobj import ConfigObj
from check_interop import wait_for
from sx1262_model import Model
import rnode_adapter
from rnode_adapter import ADDRESS, serve
from rnode_link import NAME
from rnode_metrics import Publisher
from rnode_wire import split_frames


def check(hold, patched_host):
    assert {name for _, name in socket.if_nameindex()} == {"lo"}
    assert not any(Path("/dev").glob("spidev*")) and not any(Path("/dev").glob("gpiochip*"))
    runtime = Path(os.environ["RUNTIME_DIRECTORY"])
    publisher = Publisher(runtime, 500_000)
    model = Model(500_000)
    received = queue.Queue()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    class Owner:
        def inbound(self, data, interface):
            received.put((bytes(data), interface.r_stat_rssi, interface.r_stat_snr))

    with tempfile.TemporaryDirectory() as tmp, socket.create_server(ADDRESS) as listener:
        Path(tmp, "config").write_text("[reticulum]\n  share_instance = no\n[interfaces]\n")
        RNS.Reticulum(configdir=tmp)
        thread = threading.Thread(target=serve, args=(model.radio, listener, stop.is_set, publisher))
        thread.start()
        iface = None
        try:
            snippet = Path(rnode_adapter.__file__).with_name("rnode-interface.conf").read_text()
            config = ConfigObj(("[interfaces]\n" + snippet).splitlines())["interfaces"][NAME].dict()
            iface = RNodeInterface(Owner(), dict(config, name=NAME))
            assert iface.online
            for snr_raw, expected in ((0, 0), (17, 4.25), (0xe3, -7.25), (0xc0, -16), (0xdb,-9.25)):
                data = bytes((snr_raw, 0xc0, 0xdb))
                model.frames.put((2,b"\x30"+data,(202,snr_raw,0)))
                payload, dbm, db = received.get(timeout=4)
                host_expected = expected if patched_host else {0xc0:-9, 0xdb:-8.75}.get(snr_raw, expected)
                assert (payload, dbm, db) == (data, -101, host_expected), (snr_raw, db, expected)
                wait_for(lambda: json.loads(publisher.path.read_text())["last"] is not None and
                         json.loads(publisher.path.read_text())["last"]["snr_db"] == expected)
                print(f"GetPacketStatus SNR {expected:g} dB, RNS client {db:g} dB", flush=True)

            model.frames.put((0x42,b"bad"))
            model.frames.put((2,b"\x51"+b"x"*254))
            model.frames.put((0x22,b"bad header"))
            model.frames.put((2,b"\x61orphan"))
            data = b"z"*300
            first, last = split_frames(data, 7)
            model.frames.put((2,first,(160,12,255)))
            model.frames.put((2,last,(207,0xe3,80)))
            assert received.get(timeout=4) == (data, -103, -7.25)
            wait_for(lambda: json.loads(publisher.path.read_text())["packets"] == 6)
            record = json.loads(publisher.path.read_text())
            assert (record["frames"],record["crc"],record["header_errors"],record["incomplete"],
                    record["orphans"],record["pending"]) == (9,1,1,1,1,False), record
            assert record["last"]["rssi_dbm"] == -103.5 and record["last"]["snr_db"] == -7.25
            print("PASS: 9 valid frames, 6 complete packets, CRC=1, header=1, abandoned=1, orphan=1; last fragment -103.5 dBm / -7.25 dB", flush=True)
            if hold:
                # Hold the verified sample for the actual SXMD01 terminal; no test traffic after this point.
                stop.wait(240)
        finally:
            if iface:
                iface.detach()
            stop.set()
            thread.join(4)
            assert not thread.is_alive()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--hold", action="store_true")
    cli.add_argument("--patched-host", action="store_true")
    args = cli.parse_args()
    check(args.hold, args.patched_host)
