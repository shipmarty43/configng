#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the Zero 2W overlay and check both the stock and merged binary graphs."""
import argparse
import hashlib
import shutil
from pathlib import Path
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
STOCK = "4b90c01af0137b2297fb7243f200c5b32c33ce7e9b0e3d15fbde8c9733363758"
TVE = "/soc/tv-encoder@6520000"
JACK = "/cvbs-connector"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


class Tree:
    def __init__(self, path):
        self.path = path

    def prop(self, node, name, fmt="s"):
        return run("fdtget", "-t", fmt, self.path, node, name).split()

    def cells(self, node, name):
        return [int(value, 16) for value in self.prop(node, name, "x")]

    def symbol(self, name):
        return self.prop("/__symbols__", name)[0]

    def handle(self, node):
        return self.cells(node, "phandle")[0]

    def enabled(self, node):
        props = run("fdtget", "-p", self.path, node).split()
        return "status" not in props or self.prop(node, "status") in (["okay"], ["ok"])

    def link(self, first, second, *, active=True):
        for local, remote in ((first, second), (second, first)):
            if active:
                check(self.enabled(local), f"disabled endpoint {local}")
            check(self.cells(local, "remote-endpoint") == [self.handle(remote)],
                  f"broken remote-endpoint at {local}")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify_base(tree):
    check("xunlong,orangepi-zero2w" in tree.prop("/", "compatible"), "wrong board")
    for label in ("tcon_tv0", "tcon_top", "hdmi"):
        check(tree.enabled(tree.symbol(label)), f"{label} disabled in base")
    check("tv-encoder@6520000" not in run("fdtget", "-l", tree.path, "/soc").split(),
          "base already contains TVE")
    verify_hdmi_links(tree)


def verify_hdmi_links(tree, *, active=True):
    first, second = tree.symbol("tcon_tv0_out_tcon_top"), tree.symbol("tcon_top_hdmi_in_tcon_tv0")
    tree.link(first, second, active=active)
    check(tree.enabled(first) == active and tree.enabled(second) == active, "HDMI branch status")
    tree.link(tree.symbol("tcon_top_hdmi_out_hdmi"), tree.symbol("hdmi_in_tcon_top"))
    tree.link(tree.symbol("hdmi_out_con"), tree.symbol("hdmi_con_in"))


def verify_profile(tree):
    top, tcon, ccu, sid = (tree.symbol(name) for name in ("tcon_top", "tcon_tv0", "ccu", "sid"))
    for node in (TVE, JACK, top, tcon):
        check(tree.enabled(node), f"{node} unavailable")
    check(not tree.enabled(tree.symbol("hdmi")), "HDMI and TVE both own TV0")
    verify_hdmi_links(tree, active=False)
    tree.link(tree.symbol("mixer0_out_tcon_top_mixer0"), tree.symbol("tcon_top_mixer0_in_mixer0"))
    tree.link(tree.symbol("tcon_top_mixer0_out_tcon_tv0"), tree.symbol("tcon_tv0_in_tcon_top_mixer0"))
    tree.link(tcon + "/ports/port@1/endpoint@0", TVE + "/ports/port@0/endpoint")
    tree.link(TVE + "/ports/port@1/endpoint", JACK + "/port/endpoint")
    check(tree.prop(JACK, "compatible") == ["composite-video-connector"], "jack binding")
    check(tree.prop(TVE, "compatible") == ["allwinner,sun50i-h618-tv-encoder"], "TVE binding")
    c = tree.handle(ccu)
    trim = sid + "/nvmem-layout/tv-calibration@2c"
    resources = [
        (TVE, "reg", [0x6520000, 0x100, 0x6524000, 0x3fc]),
        (TVE, "clocks", [c, 124, c, 123, c, 125]),
        (TVE, "resets", [c, 56, c, 57]),
        (TVE, "nvmem-cells", [tree.handle(trim)]),
        (trim, "reg", [0x2c, 4]),
        (sid + "/ephy-calibration@2c", "reg", [0x2c, 2]),
        (top, "clocks", [c, 118, c, 119, c, 123]),
        (top, "assigned-clocks", [c, 123]),
        (top, "assigned-clock-rates", [216000000]),
    ]
    for node, key, expected in resources:
        check(tree.cells(node, key) == expected, f"{node}: wrong {key}")
    for node, key, expected in [
        (TVE, "reg-names", ["top", "encoder"]),
        (TVE, "clock-names", ["top-bus", "tve", "bus"]),
        (TVE, "reset-names", ["top", "encoder"]),
        (TVE, "nvmem-cell-names", ["tvout"]),
        (top, "clock-names", ["bus", "tcon-tv0", "tve0"]),
        (sid + "/nvmem-layout", "compatible", ["fixed-layout"]),
    ]:
        check(tree.prop(node, key) == expected, f"{node}: wrong {key}")


def verify_rejections(merged, scratch):
    original, tree = Tree(merged), Tree(scratch)
    for node, prop, fmt, bad, diagnostic in [
        (original.symbol("hdmi"), "status", "s", ["okay"], "both own TV0"),
        (TVE + "/ports/port@0/endpoint", "remote-endpoint", "x", ["0"], "broken remote-endpoint"),
        (original.symbol("tv_trim"), "reg", "x", ["2c", "2"], "wrong reg"),
    ]:
        shutil.copyfile(merged, scratch)
        run("fdtput", "-t", fmt, scratch, node, prop, *bad)
        try:
            verify_profile(tree)
        except ValueError as error:
            if diagnostic not in str(error):
                raise
        else:
            raise ValueError(f"accepted invalid {node}/{prop}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path, help="unmodified Armbian Zero 2W DTB")
    parser.add_argument("kernel", type=Path, help="kernel source or headers with include/dt-bindings")
    parser.add_argument("--output", type=Path, help="new directory to keep the DTBO and merged DTB")
    args = parser.parse_args()
    digest = hashlib.sha256(args.dtb.read_bytes()).hexdigest()
    print(f"Base SHA-256 {digest} ({'archived image' if digest == STOCK else 'other revision'})")
    verify_base(Tree(args.dtb))
    with tempfile.TemporaryDirectory() as tmp:
        out = args.output or Path(tmp)
        if args.output:
            out.mkdir()
        overlay, merged = out / "zero2w-cvbs.dtbo", out / "zero2w-cvbs.dtb"
        source = run("cpp", "-nostdinc", "-undef", "-x", "assembler-with-cpp", "-P",
                     "-I", args.kernel / "include", SOURCE / "zero2w-cvbs.dts")
        subprocess.run(["dtc", "-@", "-I", "dts", "-O", "dtb", "-o", overlay],
                       input=source, text=True, check=True)
        run("fdtoverlay", "-i", args.dtb, "-o", merged, overlay)
        verify_profile(Tree(merged))
        verify_rejections(merged, Path(tmp) / "invalid.dtb")
        print("PASS: reciprocal mixer/TCON/TVE/DAC0 connector graph, exclusive HDMI,"
              " CCU, resets and SID cells; 3 invalid profiles rejected")


if __name__ == "__main__":
    main()
