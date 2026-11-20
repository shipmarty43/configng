"""Receive-only Waveshare SX1262 transport for the RNode profile on ARM64 Linux."""
import ctypes
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import struct
import time

FREQUENCY = 433_875_000
BANDWIDTH = 125_000
SF, CR, PREAMBLE = 9, 5, 18
# Linux spidev.h: _IOW/_IOR('k', nr, size), and struct spi_ioc_transfer.
TRANSFER = struct.Struct("=QQIIHBBBBBB")
WR = 0x40006B00
RD = 0x80006B00


class Spi:
    def __init__(self, fd, hz, ioctl=fcntl.ioctl):
        self.fd, self.hz, self.ioctl = fd, hz, ioctl
        for nr, fmt, value in ((5, "=I", 0), (2, "=B", 0), (3, "=B", 8), (4, "=I", hz)):
            raw = struct.pack(fmt, value)
            size = len(raw) << 16
            ioctl(fd, WR | size | nr, raw)
            actual = bytearray(len(raw))
            ioctl(fd, RD | size | nr, actual)
            if actual != raw:
                raise OSError(f"SPI setting {nr} readback mismatch")

    def transfer(self, data):
        tx = ctypes.create_string_buffer(data, len(data))
        rx = ctypes.create_string_buffer(len(data))
        msg = TRANSFER.pack(ctypes.addressof(tx), ctypes.addressof(rx), len(data), self.hz, 0, 8, 0, 0, 0, 0, 0)
        # Mutable buffer preserves ioctl's integer transfer count.
        if self.ioctl(self.fd, WR | (TRANSFER.size << 16), bytearray(msg)) != len(data):
            raise OSError("Incomplete SPI transfer")
        return rx.raw


class Pins:
    def __init__(self, route, stack):
        import gpiod
        from gpiod.line import Direction, Value
        chip = stack.enter_context(gpiod.Chip(f"/dev/gpiochip{route.chip}"))
        self.lines = {}
        self.active, self.low = Value.ACTIVE, Value.INACTIVE
        for n in (76, 260, 257, 271):
            settings = gpiod.LineSettings(direction=Direction.INPUT if n in (76,260) else Direction.OUTPUT,
                                          output_value=Value.ACTIVE if n == 257 else Value.INACTIVE)
            self.lines[n] = stack.enter_context(chip.request_lines({n: settings}, consumer="opi-rnode-rx"))

    def read(self, n):
        return self.lines[n].get_value(n) == self.active

    def write(self, n, high):
        self.lines[n].set_value(n, self.active if high else self.low)


@dataclass(frozen=True)
class Reception:
    frame: bytes
    irq: int
    rssi_dbm: float | None = None
    snr_quarters: int | None = None


class Receiver:
    # Intentionally no SetTx, CAD, write FIFO, PA selection or test-wave command.
    COMMANDS = frozenset((0x80,0xc0,0x89,0x98,0x96,0x8a,0x11,0x9d,0x86,0x8b,0x8c,
                          0x1d,0x0d,0x8f,0x08,0x02,0x82,0x12,0x13,0x14,0x1e))

    def __init__(self, spi, pins):
        self.spi, self.pins = spi, pins

    @classmethod
    def open(cls, route, hz, stack):
        fd = os.open(Path("/dev")/route.spi, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        stack.callback(os.close, fd)
        result = cls(Spi(fd, hz), Pins(route, stack))
        stack.callback(result.off)
        result.initialize()
        return result

    def wait_busy(self):
        end = time.monotonic()+0.5
        while self.pins.read(260):
            if time.monotonic() >= end:
                raise OSError("SX1262 BUSY did not clear")
            time.sleep(.001)

    def command(self, op, args=b"", read=0):
        if op not in self.COMMANDS:
            raise ValueError("SX1262 opcode outside RX profile")
        self.wait_busy()
        data = bytes([op]) + args + (bytes(1+read) if read else b"")
        result = self.spi.transfer(data)
        if len(result) > 1 and (result[1] in (0, 255) or ((result[1] >> 1) & 7) in (3,4,5)):
            raise OSError(f"SX1262 rejected opcode 0x{op:02x}")
        return result[-read:] if read else b""

    def initialize(self):
        self.pins.write(257, False)
        time.sleep(.01)
        self.pins.write(257, True)
        time.sleep(.01)
        self.off()
        if self.command(0x1d, b"\x03\x20", 6) != b"SX1261":
            raise OSError("SX126x silicon family readback failed")
        self.command(0x89, b"\x7f")              # RC/PLL/ADC calibration
        time.sleep(.005)
        self.command(0x98, b"\x6b\x6f")         # 430–440 MHz image calibration
        self.command(0x96, b"\x01")              # DC-DC
        self.command(0x8a, b"\x01")
        if self.command(0x11, read=1) != b"\x01":
            raise OSError("LoRa packet type readback failed")
        self.command(0x9d, b"\x01")              # DIO2 RF switch, crystal on this HAT
        self.command(0x86, round(FREQUENCY * 2**25 / 32_000_000).to_bytes(4, "big"))
        self.command(0x8b, bytes([SF, 4, CR-4, 0]))  # BW125, 4/5, LDRO off
        self.command(0x8c, PREAMBLE.to_bytes(2,"big") + bytes([0,255,1,0]))  # explicit, CRC, standard IQ
        iq = self.command(0x1d, b"\x07\x36", 1)[0]
        self.command(0x0d, bytes([7,0x36,iq | 4]))  # SX1262 IQ polarity erratum
        self.command(0x0d, b"\x07\x40\x14\x24")
        if self.command(0x1d, b"\x07\x40", 2) != b"\x14\x24":
            raise OSError("RNode sync word readback failed")
        self.command(0x0d, b"\x08\xac\x96")     # boosted RX gain
        self.command(0x8f, bytes(2))
        self.command(0x08, b"\x00\x62\x00\x62\x00\x00\x00\x00")  # DIO1: RX done, header/CRC error

    def off(self):
        try:
            self.command(0x80, b"\x00")
        finally:
            self.pins.write(271, False)

    def on(self):
        self.command(0x02, b"\xff\xff")
        self.pins.write(271, True)
        self.command(0x82, b"\xff\xff\xff")

    def read_event(self):
        if not self.pins.read(76):
            return None
        self.off()
        flags = int.from_bytes(self.command(0x12, read=2), "big")
        if flags & 0x60 or not flags & 2:
            self.on()
            return Reception(b"", flags)
        count, start = self.command(0x13, read=2)
        frame = self.command(0x1e, bytes([start]), count) if count else b""
        if frame:
            # GetPacketStatus is latched to this frame. Capture before SetRx.
            rssi, snr, _signal_rssi = self.command(0x14, read=3)
            result = Reception(frame, flags, -rssi / 2, snr if snr < 128 else snr - 256)
        else:
            result = Reception(b"", flags)
        self.on()
        return result

    def poll(self):
        """Compatibility for callers that only consume FIFO data."""
        event = self.read_event()
        return event.frame if event is not None else None

    def send(self, payload):
        raise PermissionError("Hardware TX is disabled")
