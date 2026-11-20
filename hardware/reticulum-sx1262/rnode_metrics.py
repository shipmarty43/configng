"""Per-worker RNode RX counters and an atomic diagnostic snapshot in /run."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from rnode_wire import Reassembly, kiss


class RxMetrics:
    def __init__(self):
        self.reassembly = Reassembly()
        self.frames = self.packets = self.crc = self.header_errors = 0
        self.last = None
        self.host = "disconnected"

    def consume(self, event, now):
        self.crc += int(bool(event.irq & 0x40))
        self.header_errors += int(bool(event.irq & 0x20))
        if event.irq & 0x60 or not event.irq & 2 or not event.frame:
            self.reassembly.discard()
            return b""
        self.frames += 1
        packet = self.reassembly.accept(event.frame, now)
        if packet is None:
            return b""
        # Use the last fragment's quality for a completed datagram, as on nRF52 RNode.
        self.packets += 1
        self.last = dict(at=now, rssi_dbm=event.rssi_dbm, snr_db=event.snr_quarters / 4)
        # The RNode host protocol uses whole dBm (truncate toward zero) + 157,
        # and a two's-complement quarter-dB byte. Escape all three KISS frames.
        return (kiss(0x23, bytes([157 + int(event.rssi_dbm)]))
                + kiss(0x24, bytes([event.snr_quarters & 255])) + kiss(0, packet))

    def snapshot(self):
        return dict(host=self.host, frames=self.frames, packets=self.packets,
                    crc=self.crc, header_errors=self.header_errors,
                    incomplete=self.reassembly.abandoned, orphans=self.reassembly.orphans,
                    pending=self.reassembly.first is not None, last=self.last)


class Publisher:
    def __init__(self, directory, spi_hz):
        self.path = Path(directory) / "rx.json"
        self.hz = spi_hz
        self.invocation = os.environ["INVOCATION_ID"]
        self.next_write = 0
        self.write_failed = False

    def update(self, metrics, now):
        if now < self.next_write:
            return
        record = dict(version=1, invocation=self.invocation, pid=os.getpid(),
                      updated=now, spi_hz=self.hz, **metrics.snapshot())
        self.next_write = now + 1
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.path.parent, delete=False) as file:
                try:
                    json.dump(record, file, allow_nan=False)
                    file.flush()
                    os.replace(file.name, self.path)
                finally:
                    Path(file.name).unlink(missing_ok=True)
        except OSError as err:
            # A full /run must not tear down an otherwise healthy radio interface.
            if not self.write_failed:
                print(f"RNode diagnostics unavailable: {err}", file=sys.stderr, flush=True)
            self.write_failed = True
        else:
            self.write_failed = False
