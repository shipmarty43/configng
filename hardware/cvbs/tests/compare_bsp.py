# SPDX-License-Identifier: GPL-2.0-only
"""Compile the pinned BSP functions and the port into one RAM-only test."""
import argparse
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHA_C = "54309cb05bcea0e09ba264926385feefe632f96fe16a7c2de929e3b3e597a01f"
SHA_H = "19f4b6cefb1b928dae562dd9e4a60b7d9c96add88924ae315d30fd913ebb7aa2"


def checked(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit(f"Unexpected BSP revision: {path}")
    return data.decode()


def oracle(bsp):
    folder = bsp / "drivers/video/fbdev/sunxi/disp2/tv"
    src = checked(folder / "de_tve_sun8iw11.c", SHA_C)
    header = checked(folder / "de_tvec.h", SHA_H)
    # Only register I/O is substituted. Keep even the unused mode cases so that
    # the comparison exercises the vendor switch and its original control flow.
    functions = src[src.index("s32 tve_low_init("):src.index("/* 0:unconnected")]
    functions += src[src.index("s32 tve_adjust_resync("):src.index("s32 tve_low_enhance(")]
    offsets = re.findall(r"^#define TVE_(?:TOP_)?[0-9A-F]{3}\s+\(0[xX][0-9A-Fa-f]+\)$",
                         header, flags=re.MULTILINE)
    cases = re.findall(r"case (DISP_\w+):", functions)
    return ("#define TVE_DAC_NUM 1\n"
            "static u32 dac_info[1][TVE_DAC_NUM], dac_type_info[1][TVE_DAC_NUM];\n"
            + "\n".join(offsets) + "\nenum disp_tv_mode {" + ",".join(cases)
            + "};\n" + functions)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bsp", type=Path)
    ap.add_argument("--arm64", action="store_true", help="cross-compile and run with qemu-aarch64")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "vendor-oracle.inc").write_text(oracle(args.bsp))
        cc = ["aarch64-linux-gnu-gcc", "-static"] if args.arm64 else ["cc"]
        binary = root / "compare"
        subprocess.run([*cc, "-std=c11", "-O2", "-Wall", "-Werror",
                        "-I", str(HERE / "include"), "-I", tmp,
                        str(HERE / "differential.c"), str(HERE.parent / "h618-tve.c"),
                        "-o", str(binary)], check=True)
        run = ["qemu-aarch64"] if args.arm64 else []
        subprocess.run([*run, str(binary)], check=True)


if __name__ == "__main__":
    main()
