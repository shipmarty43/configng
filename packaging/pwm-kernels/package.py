#!/usr/bin/env python3
"""Build a PWM002 kernel upgrade or its rollback from the exact Armbian image package."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def control_field(root, key):
    return next(line.split(": ", 1)[1] for line in (root / "DEBIAN/control").read_text().splitlines()
                if line.startswith(key + ": "))


def modules(folder):
    return {p.relative_to(folder) for p in folder.rglob("*.ko*") if p.is_file()
            and re.search(r"\.ko(?:\.(?:gz|xz|zst))?$", p.name)}


def checksum(path, method):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, method).hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("stock", type=Path, help="Original linux-image .deb from Armbian OCI")
    cli.add_argument("version", help="Installed Debian version in the clean image")
    cli.add_argument("installed_md5", type=Path, help="Image's /var/lib/dpkg/info/PACKAGE.md5sums")
    cli.add_argument("out", type=Path)
    cli.add_argument("--build", type=Path, help="Completed kernel build directory")
    cli.add_argument("--modroot", type=Path, help="INSTALL_MOD_PATH with all stripped modules, including board extras")
    cli.add_argument("--revision", default="1")
    a = cli.parse_args()
    if bool(a.build) != bool(a.modroot) or not re.fullmatch(r"[1-9][0-9]*", a.revision):
        cli.error("--build and --modroot go together; revision must be a positive integer")
    run("dpkg", "--validate-version", a.version)
    a.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.out) as tmp:
        root = Path(tmp) / "pkg"
        run("dpkg-deb", "-R", a.stock.resolve(), root)
        manifest = root / "DEBIAN/md5sums"
        if manifest.read_bytes() != a.installed_md5.read_bytes():
            raise ValueError("OCI kernel payload differs from the installed image manifest")
        run("md5sum", "--quiet", "-c", "DEBIAN/md5sums", cwd=root)
        name = control_field(root, "Package")
        rel = control_field(root, "Armbian-Kernel-Version-Family")
        info = root / "DEBIAN/control"
        metadata = info.read_text()
        version = a.version
        if a.build:
            if (a.build / "include/config/kernel.release").read_text().strip() != rel:
                raise ValueError("Kernel release differs from the boot hooks and DT package")
            sym = (a.build / "System.map").read_text()
            if not re.search(r"\bheader_pwm_profiles_show(?:\.\w+)*$", sym, re.M):
                raise ValueError("Built-in patched PWM driver missing from System.map")
            image = a.build / "arch/arm64/boot/Image"
            with image.open("rb") as stream:
                stream.seek(56)
                if stream.read(4) != b"ARM\x64":
                    raise ValueError("Expected an ARM64 boot Image")
            old = root / "lib/modules" / rel
            new = a.modroot / "lib/modules" / rel
            expected, actual = modules(old), modules(new)
            if not expected or actual != expected:
                raise ValueError(f"Module inventory mismatch; missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
            for obj in (old, new):
                if any(p.is_symlink() and p.name not in ("build","source") for p in obj.rglob("*")):
                    raise ValueError(f"Unexpected module symlink in {obj}")
            shutil.rmtree(old)
            shutil.copytree(new, old, ignore=shutil.ignore_patterns("source", "build"))
            for src, dest in ((image,"vmlinuz"), (a.build/"System.map","System.map"), (a.build/".config","config")):
                shutil.copyfile(src,root/"boot"/(dest+"-"+rel))
            index = run("depmod", "-e", "-b", root, "-F", a.build/"System.map", rel,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if index.stdout.strip():
                raise ValueError("depmod reported module dependency problems:\n" + index.stdout)
            lines = [checksum(p,"md5") + "  " + str(p.relative_to(root)) for p in sorted(root.rglob("*"))
                     if p.is_file() and not p.is_symlink() and "DEBIAN" != p.relative_to(root).parts[0]]
            manifest.write_text("\n".join(lines) + "\n")
            version += "+pwm002." + a.revision
            metadata = metadata.replace("Armbian-Original-Hash:", "X-PWM002-Base-Artifact:")
            metadata += "X-PWM002-Profile: header_pwm_profiles\n"
            size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()) // 1024
            metadata = re.sub(r"^Installed-Size: .+$", "Installed-Size: " + str(size), metadata, flags=re.M)
        info.write_text(re.sub(r"^Version: .+$", "Version: "+version, metadata, flags=re.M))
        target = a.out / f"{name}_{version}_arm64.deb"
        built = Path(tmp)/"image.deb"
        run("dpkg-deb","--root-owner-group","--threads-max=1","-Zxz","-z3","--build",root,built)
        built.replace(target)
        print(checksum(target, "sha256"), target.name, flush=True)


if __name__ == "__main__":
    main()
