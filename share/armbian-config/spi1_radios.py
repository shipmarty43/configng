"""Select the Zero 2W radio overlay and verify the composed board tree."""
import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from dt_clock_overlay import install_blob, tokens, write_selection
from uart_routes import PIO, cells, enabled, owners, read_tree, strings

SINGLE = "opi-zero2w-sx1262"
SHARED = "opi-zero2w-spi1-radios"
BUS = "/soc/spi@5011000"
CLIENTS = (("radio@0","semtech,sx1262",16_000_000),
           ("cc1101@1","ti,cc1101",6_500_000), ("nrf24@2","nordic,nrf24l01",8_000_000))
CONTROL = {0: {"reset-gpios": (8,1,1), "busy-gpios": (8,4,0), "dio1-gpios": (2,12,0),
               "rxen-gpios": (8,15,0)}, 2: {"ce-gpios": (7,4,0)}}


def select(before, after, folder, action):
    text = before.read_text()
    current = tokens(text)
    target = {"enable": SINGLE, "shared": SHARED, "disable": None}[action]
    if target == SHARED:
        dts = Path(__file__).with_name("overlays") / (SHARED + ".dts")
        blob = subprocess.check_output(["dtc","-q","-@","-I","dts","-O","dtb",dts])
        install_blob(folder, SHARED, blob)
    providers = (SINGLE, SHARED)
    positions = [i for i,n in enumerate(current) if n in providers or n.startswith("opi-sclk-spi1-")]
    names = [n for n in current if n not in providers]
    if target:
        names.insert(min(positions, default=len(names)),target)
    write_selection(text, after, names)


def validate(dtb, base, blobs):
    # Refuse to cover up an existing SPI1 provider, even one that used the same
    # child path and whose properties our later overlay would otherwise replace.
    if sum(p.stem == SHARED for p in blobs) != 1:
        raise ValueError("Expected one shared SPI1 overlay")
    extras = [p for p in blobs if p.stem != SHARED and not p.stem.startswith("opi-sclk-spi1-")]
    if extras:
        with TemporaryDirectory() as tmp:
            other = Path(tmp)/"prior.dtb"
            subprocess.run(["fdtoverlay","-i",base,"-o",other,*extras],check=True)
            prior = read_tree(other)
    else:
        prior = read_tree(base)
    if enabled(prior, BUS):
        raise ValueError("Another overlay already enables SPI1; release its route first")

    tree = read_tree(dtb)
    if not {"xunlong,orangepi-zero2w","allwinner,sun50i-h618"} <= set(strings(tree["/"]["compatible"])):
        raise ValueError("Expected Orange Pi Zero 2W")
    pio, = cells(tree[PIO]["phandle"])
    group = tree[PIO+"/spi1-pins"]
    bus = tree[BUS]
    selects = [(8,3), (7,9), (7,5)]
    if (not enabled(tree,BUS) or bus.get("pinctrl-0") != group["phandle"] or
            strings(group["function"]) != ["spi1"] or set(strings(group["pins"])) != {"PH6","PH7","PH8"} or
            cells(bus["num-cs"]) != [3] or cells(bus["cs-gpios"]) !=
            [v for bank,bit in selects for v in (pio,bank,bit,1)]):
        raise ValueError("Expected SPI1 with three kernel chip selects on PI3, PH9 and PH5")
    expected = {BUS+"/"+name for name,_,_ in CLIENTS}
    children = {path for path,p in tree.items() if path.rpartition("/")[0]==BUS and
                "reg" in p and enabled(tree,path)}
    if children != expected:
        raise ValueError("SPI1 requires exactly the three declared radio clients")
    pads = {pin: BUS for pin in ("PH6","PH7","PH8","PI3","PH9","PH5")}
    for cs,(name,compat,limit) in enumerate(CLIENTS):
        path = BUS+"/"+name
        child = tree[path]
        speed, = cells(child["spi-max-frequency"])
        if (cells(child["reg"]) != [cs] or strings(child["compatible"]) != [compat,"armbian,spi-dev"] or
                not 3000 <= speed <= limit or any(k in child for k in
                ("spi-cs-high","spi-cpha","spi-cpol","spi-3wire","spi-lsb-first"))):
            raise ValueError(f"Invalid CS, mode or clock at {path}")
        for prop,(bank,bit,flags) in CONTROL.get(cs,{}).items():
            if cells(child[prop]) != [pio,bank,bit,flags]:
                raise ValueError(f"Unexpected {prop} at {path}")
            pads[f"P{chr(65+bank)}{bit}"] = path
    claims = owners(tree)
    for pin,owner in pads.items():
        if claims.get(pin,set()) != {owner}:
            raise ValueError(f"{pin} has conflicting owners: {sorted(claims.get(pin, set()))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op",required=True)
    cmd = sub.add_parser("select")
    for arg in ("before","after","folder"): cmd.add_argument(arg,type=Path)
    cmd.add_argument("action",choices=("enable","shared","disable"))
    cmd = sub.add_parser("validate")
    cmd.add_argument("dtb",type=Path); cmd.add_argument("base",type=Path); cmd.add_argument("blobs",nargs="*",type=Path)
    args = parser.parse_args()
    try:
        if args.op == "select": select(args.before,args.after,args.folder,args.action)
        else: validate(args.dtb,args.base,args.blobs)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
