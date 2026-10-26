"""Boundary checks for the offline firmware reader, using synthetic bytes only."""

from pathlib import Path
import struct
import tempfile
import unittest

from inspect_imagewty import find_fdts, inspect, read_items


def fixture():
    data = bytearray(3072)
    data[:8] = b"IMAGEWTY"
    struct.pack_into("<II", data, 8, 0x300, 96)
    struct.pack_into("<II", data, 20, 0x100234, len(data))
    struct.pack_into("<I", data, 60, 1)
    struct.pack_into("<II", data, 1024, 256, 1024)
    data[1060:1073] = b"../escape.dtb"
    struct.pack_into("<QQQ", data, 1316, 1024, 1024, 2048)
    # Empty root FDT: reservation terminator, tree tokens, empty strings block.
    struct.pack_into(">10I", data, 2048,
                     0xd00dfeed, 72, 56, 72, 40, 17, 16, 0, 0, 16)
    struct.pack_into(">4I", data, 2104, 1, 0, 2, 9)
    return data


class ImageReaderTests(unittest.TestCase):
    def test_output_ignores_item_path_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.bin"
            image.write_bytes(fixture())
            report = inspect(image, root / "out")
            self.assertEqual(len(report["fdt_candidates"]), 1)
            self.assertTrue((root / "out/offset-00000800.dtb").is_file())
            self.assertFalse((root / "escape.dtb").exists())
            with self.assertRaises(FileExistsError):
                inspect(image, root / "out")

    def test_truncated_and_unsupported_headers(self):
        for data in (b"", fixture()[:-1]):
            with self.assertRaises(ValueError):
                read_items(data)
        data = fixture()
        struct.pack_into("<I", data, 8, 0x403)
        with self.assertRaises(ValueError):
            read_items(data)

    def test_out_of_bounds_item(self):
        data = fixture()
        struct.pack_into("<Q", data, 1332, 3000)
        with self.assertRaises(ValueError):
            read_items(data)

    def test_fdt_cannot_cross_item_end(self):
        data = fixture()
        struct.pack_into(">I", data, 2052, 2048)
        self.assertEqual(list(find_fdts(data, read_items(data))), [])

    def test_invalid_input_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "bad.bin"
            image.write_bytes(b"invalid")
            with self.assertRaises(ValueError):
                inspect(image, root / "out")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
