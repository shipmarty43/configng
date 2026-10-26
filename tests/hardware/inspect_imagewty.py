#!/usr/bin/env python3
"""Read an unencrypted IMAGEWTY v3 image; inventory items and carve FDT candidates.

Offline research helper, not an installer. Does not mount or execute firmware.
Format reference: https://github.com/Ithamar/awutils/blob/master/imagewty.h
Carved candidates still require dtc validation and interpretation of their parent
container; their presence does not prove that a bootloader uses them.
"""

import argparse
import hashlib
import json
import mmap
from pathlib import Path
import struct


def read_items(data):
    """Validate the supported header and every item before permitting extraction."""
    if len(data) < 1024 or data[:8] != b"IMAGEWTY":
        raise ValueError("not an unencrypted IMAGEWTY image")
    version, header_size = struct.unpack_from("<II", data, 8)
    fmt, image_size = struct.unpack_from("<II", data, 20)
    if (version, header_size, fmt) != (0x300, 96, 0x100234):
        raise ValueError("unsupported IMAGEWTY format")
    if image_size != len(data):
        raise ValueError("image length differs from header")
    count = struct.unpack_from("<I", data, 60)[0]
    table_end = (count + 1) * 1024
    if not 0 < count <= 4096 or table_end > len(data):
        raise ValueError("invalid item table size")
    items = []
    for index in range(count):
        start = (index + 1) * 1024
        if struct.unpack_from("<II", data, start) != (256, 1024):
            raise ValueError("unsupported item header")
        stored, size, offset = struct.unpack_from("<QQQ", data, start + 292)
        if offset < table_end or size > stored or offset + stored > len(data):
            raise ValueError("item outside image or inconsistent lengths")
        name = data[start + 36:start + 292].split(b"\0", 1)[0].decode(
            "utf-8", errors="replace"
        )
        # Names are informational only and never used as output paths.
        items.append(dict(index=index, name=name, offset=offset,
                          size=size, stored_size=stored))
    ordered = sorted(items, key=lambda item: item["offset"])
    for left, right in zip(ordered, ordered[1:]):
        if left["offset"] + left["stored_size"] > right["offset"]:
            raise ValueError("overlapping image items")
    return items


def find_fdts(data, items):
    """Yield bounded v17 FDT candidates contained in declared image items."""
    for item in items:
        start, end = item["offset"], item["offset"] + item["size"]
        while True:
            offset = data.find(b"\xd0\x0d\xfe\xed", start, end)
            if offset < 0:
                break
            start = offset + 4
            if offset + 40 > end:
                continue
            (_, size, tree, strings, reserved, version, last, _,
             strings_size, tree_size) = struct.unpack_from(">10I", data, offset)
            if not (40 <= size <= 4 * 1024 * 1024 and offset + size <= end
                    and version == 17 and last <= 17
                    and 40 <= reserved < size
                    and 40 <= tree < size and tree + tree_size <= size
                    and 40 <= strings <= size and strings + strings_size <= size):
                continue
            yield dict(offset=offset, size=size, item_index=item["index"],
                       item_name=item["name"], item_offset=offset - item["offset"])


def inspect(image, output):
    with image.open("rb") as stream:
        if stream.seek(0, 2) < 1024:
            raise ValueError("image too small")
        stream.seek(0)
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            items = read_items(data)
            fdts = []
            for candidate in find_fdts(data, items):
                if len(fdts) >= 128:
                    raise ValueError("too many FDT candidates")
                fdts.append(candidate)
            report = dict(image_size=len(data), image_sha256=hashlib.sha256(data).hexdigest(),
                          items=items, fdt_candidates=fdts)
            # Require a new output directory; never overwrite an earlier capture.
            output.mkdir(parents=True, exist_ok=False)
            for candidate in fdts:
                offset, size = candidate["offset"], candidate["size"]
                blob = data[offset:offset + size]
                candidate["filename"] = f"offset-{offset:08x}.dtb"
                candidate["sha256"] = hashlib.sha256(blob).hexdigest()
                (output / candidate["filename"]).write_bytes(blob)
            (output / "inventory.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path, help="new output directory")
    args = parser.parse_args()
    try:
        result = inspect(args.image, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Inspection failed: {error}\n")
    print(f"{len(result['items'])} items; {len(result['fdt_candidates'])} FDT candidates")
