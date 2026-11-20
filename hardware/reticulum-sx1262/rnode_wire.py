"""Single-radio RNode host framing and normal-mode LoRa reassembly."""
import time

FEND, FESC = 0xc0, 0xdb
MTU = 508


def kiss(command, data):
    return bytes([FEND, command]) + data.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc") + bytes([FEND])


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.open = self.escape = False

    def feed(self, data):
        for byte in data:
            if byte == FEND:
                if self.open and self.buffer and not self.escape:
                    yield self.buffer[0], bytes(self.buffer[1:])
                self.open, self.escape = True, False
                self.buffer.clear()
            elif self.open:
                if self.escape:
                    if byte not in (0xdc,0xdd):
                        self.open = False
                        continue
                    byte = FEND if byte == 0xdc else FESC
                    self.escape = False
                elif byte == FESC:
                    self.escape = True
                    continue
                if len(self.buffer) >= MTU+1:
                    self.open = False
                else:
                    self.buffer.append(byte)


class Reassembly:
    def __init__(self):
        self.first = None

    def accept(self, frame, now=None):
        now = time.monotonic() if now is None else now
        if not 2 <= len(frame) <= 255 or frame[0] & 0x0e:
            self.first = None
            return None
        header, data = frame[0], frame[1:]
        if not header & 1:
            self.first = None
            return data
        first, self.first = self.first, None
        if first and first[0] == header and now-first[1] <= 10:
            return first[2] + data
        if len(data) == 254:
            self.first = (header, now, data)
        return None


def split_frames(payload, sequence):
    """Normal-mode RNode frames for virtual peer interoperability tests."""
    if not 1 <= len(payload) <= MTU or not 0 <= sequence < 16:
        raise ValueError("Invalid RNode packet size or sequence")
    header = bytes([(sequence << 4) | int(len(payload) > 254)])
    return [header + payload[i:i+254] for i in range(0,len(payload),254)]
