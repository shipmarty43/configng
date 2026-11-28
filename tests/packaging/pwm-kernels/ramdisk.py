"""Verify the Armbian U-Boot ramdisk header, checksums and matching Linux initramfs."""
import hashlib
from pathlib import Path
import struct
import sys
import zlib

boot = Path("/boot")
release, = sys.argv[1:]
with (boot / ("uInitrd-" + release)).open("rb") as wrapper:
    header = bytearray(wrapper.read(64))
    magic, hcrc, _, size, _, _, dcrc, _, _, kind = struct.unpack_from(">7I3B", header)
    header[4:8] = bytes(4)
    if magic != 0x27051956 or kind != 3 or zlib.crc32(header) != hcrc:
        sys.exit("Invalid U-Boot ramdisk header")
    total = crc = 0
    digest = hashlib.sha256()
    while chunk := wrapper.read(1024*1024):
        total += len(chunk)
        crc = zlib.crc32(chunk, crc)
        digest.update(chunk)
with (boot / ("initrd.img-" + release)).open("rb") as initrd:
    if total != size or crc != dcrc or hashlib.file_digest(initrd,"sha256").digest() != digest.digest():
        sys.exit("uInitrd payload differs from the selected initramfs")
print("U-Boot ramdisk verified", release, size, digest.hexdigest())
