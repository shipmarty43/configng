"""Bundle a verified board kernel, its rollback, configurator and matched helper modules."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def field(deb, key):
    return subprocess.check_output(["dpkg-deb","-f",deb,key],text=True).strip()


def assemble(kernel_kit, config, gpio, modules, out, wiringpi):
    stock, = (kernel_kit/"rollback").glob("*.deb")
    pwm, = (kernel_kit/"current").glob("*.deb")
    abi = field(pwm,"Armbian-Kernel-Version-Family")
    name = field(pwm,"Package")
    board, expected = {"linux-image-current-sunxi64": ("orangepizero2w", {"dfr0528_battery","opi_i2c_recovery"}),
                       "linux-image-vendor-sun60iw2": ("orangepizero3w", {"opi_i2c_recovery"})}[name]
    if (field(stock,"Package") != name or field(stock,"Armbian-Kernel-Version-Family") != abi or
            field(gpio,"Package") != "opi-header-gpio-modules-"+abi or field(config,"Package") != "armbian-config-zero2w"):
        raise ValueError("Kernel, configurator or GPIO module package mismatch")
    if field(wiringpi,"Package") != "wiringpi-orange-gpio" or field(wiringpi,"Architecture") != "arm64":
        raise ValueError("Expected the ARM64 board GPIO package")
    if {m.stem for m in modules} != expected or len(expected) != len(modules):
        raise ValueError(f"Expected helper modules {expected}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        root=Path(tmp)/"package"; kit=Path(tmp)/"kit"
        for folder in ("support","current","rollback"):
            (kit/folder).mkdir(parents=True)
        helpers="opi-board-helpers-"+abi
        dest=root/"usr/lib/modules"/abi/"updates/opi-board-helpers"; dest.mkdir(parents=True)
        for module in modules:
            for key,want in (("name",module.stem),("vermagic",abi)):
                if subprocess.check_output(["modinfo","-F",key,module],text=True).split()[0] != want:
                    raise ValueError(f"Module {module} does not match {abi}")
            shutil.copyfile(module,dest/module.name)
        meta=root/"DEBIAN"; meta.mkdir()
        version=field(config,"Version")
        (meta/"control").write_text(f"Package: {helpers}\nVersion: {version}\nArchitecture: arm64\nDepends: kmod\nMaintainer: Orange Pi configurator maintainers <shipmarty43@users.noreply.github.com>\nDescription: I2C diagnostics and board support for {abi}\n")
        for action in ("postinst","postrm"):
            script=meta/action; script.write_text(f"#!/bin/sh\nset -e\nif [ -f /lib/modules/{abi}/modules.order ]; then depmod -a {abi}; fi\n");script.chmod(0o755)
        subprocess.run(["dpkg-deb","--root-owner-group","--threads-max=1","--build",root,kit/"support"/f"{helpers}_{version}_arm64.deb"],check=True)
        for src,folder in ((stock,"rollback"),(pwm,"current"),(config,"support"),(gpio,"support"),(wiringpi,"support")):
            shutil.copy2(src,kit/folder/src.name)
        shutil.copy2(Path(__file__).with_name("kit.sh"),kit/"apply.sh")
        (kit/"board.txt").write_text(f"{board} {name} {abi} {field(stock,'Version')} {field(pwm,'Version')}\n")
        lines=[]
        for f in sorted(kit.rglob("*")):
            if f.is_file():
                with f.open("rb") as stream:
                    lines.append(hashlib.file_digest(stream,"sha256").hexdigest()+"  "+str(f.relative_to(kit)))
        (kit/"SHA256SUMS").write_text("\n".join(lines)+"\n")
        os.rename(kit,out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("kernel_kit","config","gpio","out"):
        parser.add_argument(name,type=Path)
    parser.add_argument("--wiringpi",type=Path,required=True)
    parser.add_argument("modules",nargs="+",type=Path)
    a=parser.parse_args()
    assemble(a.kernel_kit,a.config,a.gpio,a.modules,a.out,a.wiringpi)
