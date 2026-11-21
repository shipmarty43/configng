"""Memory-backed SX1262 SPI ioctl, GPIO, FIFO and DIO1 model."""
import ctypes
import queue
import sys

from sx1262_rx import RD, WR, TRANSFER, Receiver, Spi


class Model:
    def __init__(self, hz, radio_type=Receiver):
        self.hz = hz
        self.settings = {}
        self.levels = {}
        self.frames = queue.Queue()
        self.pending = None
        self.registers = dict(enumerate(b"SX1261", 0x320))
        self.ops = []
        self.mode = "standby"
        self.fifo = b""
        self.tx_irq = 0
        self.tx_result = 1  # 0x0200 simulates chip timeout, 0 a missing IRQ
        self.out = queue.Queue()
        self.emit = self.out.put
        self.spi = Spi(-1, hz, self.ioctl)
        self.radio = radio_type(self.spi, self)
        self.radio.initialize()

    def receive_from_peer(self, frame):
        if self.mode == "rx" and self.levels[271]:
            self.frames.put((2, frame))  # RxDone

    def write(self, line, high):
        assert line in (257, 271)
        self.levels[line] = high

    def read(self, line):
        if line == 260:
            return False
        assert line == 76
        if self.mode != "rx":
            return bool(self.tx_irq & self.mask)
        if self.pending is None:
            try:
                self.pending = self.frames.get_nowait()
            except queue.Empty:
                return False
        return bool(self.pending[0] & self.mask)

    def ioctl(self, fd, request, arg):
        assert fd == -1
        nr = request & 255
        if nr:
            size, expected = {5: (4, 0), 2: (1, 0), 3: (1, 8), 4: (4, self.hz)}[nr]
            assert len(arg) == size
            if request == WR | size << 16 | nr:
                assert int.from_bytes(arg, sys.byteorder) == expected
                self.settings[nr] = bytes(arg)
            else:
                assert request == RD | size << 16 | nr
                arg[:] = self.settings[nr]
            return 0
        assert request == WR | 32 << 16 and len(arg) == 32 and len(self.settings) == 4
        txbuf, rxbuf, size, rate, delay, bits, cs, *other = TRANSFER.unpack(arg)
        assert rate == self.hz and bits == 8 and not (cs or delay or any(other))
        tx = ctypes.string_at(txbuf, size)
        self.ops.append(tx)
        rx = self.exchange(tx)
        ctypes.memmove(rxbuf, bytes(rx), size)
        return size

    def exchange(self, tx):
        op = tx[0]
        rx = bytearray(len(tx))
        rx[1] = 0x22
        if op == 0x80:
            self.mode = "standby"
        elif op == 0x11:
            rx[2] = 1
        elif op == 0x0d:
            self.registers.update(enumerate(tx[3:], int.from_bytes(tx[1:3], "big")))
        elif op == 0x1d:
            addr = int.from_bytes(tx[1:3], "big")
            rx[4:] = bytes(self.registers.get(addr + i, 0) for i in range(len(rx) - 4))
        elif op == 0x8c:
            assert self.mode == "standby" and tx[1:4] == b"\x00\x12\x00" and tx[5:] == b"\x01\x00"
            self.length = tx[4]
        elif op == 0x08:
            assert tx[1:3] == tx[3:5] and tx[5:] == bytes(4)
            self.mask = int.from_bytes(tx[1:3], "big")
        elif op == 0x02:
            assert tx[1:] == b"\xff\xff"
            self.pending = None
            self.tx_irq = 0
        elif op == 0x82:
            assert self.levels[271] and self.mask == 0x62 and self.length == 255
            self.mode = "rx"
        elif op == 0x12:
            flags = self.pending[0] if self.pending else self.tx_irq
            rx[2:4] = flags.to_bytes(2, "big")
        elif op == 0x13:
            rx[2:4] = bytes([len(self.pending[1]), 7])
        elif op == 0x1e:
            assert tx[1] == 7 and len(tx) == 3 + len(self.pending[1])
            rx[3:] = self.pending[1]
        elif op == 0x14:
            assert len(tx) == 5 and self.pending[0] == 2
            rx[2:5] = self.pending[2] if len(self.pending) > 2 else (207, 0xe3, 80)
        elif op == 0x95:
            assert tx[1:] == bytes.fromhex("04 07 00 01")
            self.pa_configured = True
        elif op == 0x8e:
            assert self.pa_configured and tx[1:] == bytes.fromhex("00 02")
            self.power_configured = True
        elif op == 0x0e:
            assert self.mode == "standby" and tx[1] == 0 and len(tx[2:]) == self.length
            self.fifo = tx[2:]
        elif op == 0x83:
            assert self.power_configured and not self.levels[271] and self.mode == "standby"
            assert self.mask == 0x0201 and not self.tx_irq and len(self.fifo) == self.length
            assert len(tx) == 4 and int.from_bytes(tx[1:], "big") > 0
            self.mode = "tx"
            self.tx_irq = self.tx_result
            if self.tx_irq == 1:
                self.emit(self.fifo)
            self.fifo = b""
        else:
            assert op in (0x89, 0x98, 0x96, 0x8a, 0x9d, 0x86, 0x8b, 0x8f), hex(op)
        return rx
