"""SX1262 half-duplex RNode transport. Only the twin constructs this backend."""
import secrets
import time

from rnode_wire import split_frames
from sx1262_rx import Radio, TransmitError


class Transceiver(Radio):
    COMMANDS = Radio.COMMANDS | {0x95, 0x8e, 0x0e, 0x83}
    # A 255-byte frame at SF9 / BW125 / CR4/5 with an 18-symbol preamble
    # takes about 1.3 s. Bound the chip timer and the independent host wait.
    TX_TICKS = 2 * 64_000
    HOST_TIMEOUT = 2.25

    def initialize(self):
        super().initialize()
        clamp = self.command(0x1d, b"\x08\xd8", 1)[0]
        self.command(0x0d, bytes([0x08, 0xd8, clamp | 0x1e]))
        modulation = self.command(0x1d, b"\x08\x89", 1)[0]
        self.command(0x0d, bytes([0x08, 0x89, modulation | 4]))  # BW125 erratum
        self.command(0x95, b"\x04\x07\x00\x01")  # SX1262 PA, standard lookup table
        self.command(0x8e, b"\x00\x02")  # fixed host profile: 0 dBm, 40 µs ramp
        self.sequence = secrets.randbelow(16)

    def send(self, payload):
        frames = split_frames(payload, self.sequence)
        self.sequence = (self.sequence + 1) % 16
        try:
            for frame in frames:
                self.off()  # standby, external RXen low
                self.irq_mask(0x0201)  # Timeout | TxDone
                self.packet_length(len(frame))
                self.command(0x02, b"\xff\xff")
                self.command(0x0e, b"\x00" + frame)  # WriteBuffer at TX base 0
                self.command(0x83, self.TX_TICKS.to_bytes(3, "big"))
                self.wait_tx_done()
        except OSError as error:
            raise TransmitError(str(error)) from error
        finally:
            # A restore failure must propagate: the worker cannot advertise READY.
            self.off()
            self.packet_length(255)
            self.irq_mask(0x62)
            self.on()

    def wait_tx_done(self):
        deadline = time.monotonic() + self.HOST_TIMEOUT
        while time.monotonic() < deadline:
            if self.pins.read(76):
                flags = int.from_bytes(self.command(0x12, read=2), "big")
                if flags & 0x0200:
                    raise TimeoutError("SX1262 TX timeout IRQ")
                if flags & 1:
                    return
            time.sleep(.002)
        raise TimeoutError("No SX1262 TxDone IRQ")
