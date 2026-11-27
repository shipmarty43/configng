#!/usr/bin/env python3
"""Build the configurator, mesh services and fixed ARM64 runtime from an offline input set."""
import argparse
import base64
import csv
import hashlib
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NATIVE = "meshtasticd_2.7.26.61~ppa54e0d8d~resolute_arm64.deb"
CORE, MESH, RUNTIME = "armbian-config-zero2w", "opi-zero2w-mesh", "opi-zero2w-mesh-runtime"
PREFIX = Path("opt/armbian-config-zero2w")
MESH_DIR = Path("opt/opi-mesh")
UNITS = Path("usr/lib/systemd/system")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    path.chmod(mode)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_inputs(inputs):
    expected = set()
    for line in (HERE / "inputs.sha256").read_text().splitlines():
        sha, name = line.split(maxsplit=1)
        if digest(inputs / name) != sha:
            raise ValueError(f"Incorrect checksum: {name}")
        if name.startswith("wheels/"):
            expected.add(Path(name).name)
    if {p.name for p in (inputs / "wheels").glob("*.whl")} != expected:
        raise ValueError("Wheel set differs from lock manifest")


def archive_source(rev, dest):
    with subprocess.Popen(["git", "-C", str(REPO), "archive", rev], stdout=subprocess.PIPE) as git:
        with tarfile.open(fileobj=git.stdout, mode="r|") as archive:
            archive.extractall(dest, filter="data")
        if git.wait():
            raise RuntimeError("git archive failed")


def package(root, name, version, arch, depends, rev, description, out, env):
    sums = []
    installed_kib = 0
    for p in sorted(root.rglob("*")):
        if p.relative_to(root).parts[0] == "DEBIAN":
            continue
        if p.is_file() and not p.is_symlink():
            installed_kib += (p.stat().st_size + 1023) // 1024
            with p.open("rb") as stream:
                sums.append(f"{hashlib.file_digest(stream, 'md5').hexdigest()}  {p.relative_to(root)}\n")
        else:
            installed_kib += 1
    write(root / "DEBIAN/md5sums", "".join(sums))
    write(root / "DEBIAN/control", f"""Package: {name}
Version: {version}
Architecture: {arch}
Installed-Size: {installed_kib}
Maintainer: Zero 2W configurator maintainers <shipmarty43@users.noreply.github.com>
Section: admin
Priority: optional
Depends: {depends}
X-Source-Revision: {rev}
Description: {description}
""")
    path = out / f"{name}_{version}_{arch}.deb"
    tmp = path.with_suffix(".deb.partial")
    try:
        run("dpkg-deb", "--root-owner-group", "--threads-max=1", "-Zxz", "-z3", "--build", root, tmp, env=env)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def reload_units(root, init_test_lock=False):
    command = "systemd-tmpfiles --create opi-sx1262-test.conf\n" if init_test_lock else ""
    write(root / "DEBIAN/postinst", "#!/bin/sh\nset -eu\n" + command +
          "if [ -d /run/systemd/system ]; then systemctl daemon-reload; fi\n", 0o755)
    write(root / "DEBIAN/postrm", "#!/bin/sh\nset -eu\nif [ -d /run/systemd/system ]; then systemctl daemon-reload; fi\n", 0o755)


def core_files(src, root):
    run("bash", str(src / "tools/config-assemble.sh"), "-p", cwd=src, stdout=subprocess.DEVNULL)
    prefix = root / PREFIX
    for directory in ("bin", "lib", "share/armbian-config", "tools/modules/desktops"):
        path = src / directory
        shutil.copytree(path, prefix / directory)
    shutil.copytree(src / "tools/modules/system/runner-cleanup", prefix / "lib/armbian-config/runner-cleanup")
    copy(src / "LICENSE", root / f"usr/share/doc/{CORE}/copyright")
    write(root / "usr/bin/armbian-config-zero2w", '#!/bin/sh\nexec /opt/armbian-config-zero2w/bin/armbian-config "$@"\n', 0o755)
    radio = src / "hardware/sx1262-mode"
    copy(radio / "opi-sx1262-test@.service", root / UNITS / "opi-sx1262-test@.service")
    restore = (radio / "opi-sx1262-restore.service").read_text().replace(
        "/usr/share/armbian-config/", "/opt/armbian-config-zero2w/share/armbian-config/")
    write(root / UNITS / "opi-sx1262-restore.service", restore)
    copy(radio / "opi-sx1262-test.conf", root / "usr/lib/tmpfiles.d/opi-sx1262-test.conf")
    pwm = src / "hardware/h616-io/opi-zero2w-pwm.service"
    if pwm.exists():
        write(root / UNITS / pwm.name, pwm.read_text().replace(
            "/usr/share/armbian-config/", "/opt/armbian-config-zero2w/share/armbian-config/"))
        extra = pwm.with_name("opi-zero2w-pwm@.service")
        stop = 'if [ -d /run/systemd/system ] && systemctl is-active --quiet opi-zero2w-pwm.service; then\n    systemctl stop opi-zero2w-pwm.service\nfi\n'
        if extra.exists():
            write(root / UNITS / extra.name, extra.read_text().replace(
                "/usr/share/armbian-config/", "/opt/armbian-config-zero2w/share/armbian-config/"))
            stop = ("if [ -d /run/systemd/system ]; then\n"
                    "    systemctl stop opi-zero2w-pwm.service opi-zero2w-pwm@2.service "
                    "opi-zero2w-pwm@3.service opi-zero2w-pwm@4.service\nfi\n")
        write(root / "DEBIAN/prerm", "#!/bin/sh\nset -eu\n" + stop, 0o755)
    uart = src / "hardware/h616-io/opi-zero2w-uart@.service"
    if uart.exists():
        write(root / UNITS / uart.name, uart.read_text().replace(
            "/usr/share/armbian-config/", "/opt/armbian-config-zero2w/share/armbian-config/"))
        rule = uart.parent / "80-opi-zero2w-uart.rules"
        copy(rule, root / "usr/lib/udev/rules.d" / rule.name)
    a733 = src / "hardware/a733-io"
    if a733.is_dir():
        unit = a733 / "opi-a733-uart@.service"
        write(root / UNITS / unit.name, unit.read_text().replace(
            "/usr/share/armbian-config/", "/opt/armbian-config-zero2w/share/armbian-config/"))
        rule = a733 / "80-opi-a733-uart.rules"
        copy(rule, root / "usr/lib/udev/rules.d" / rule.name)
    for patch in ("h616-io/patches/pwm-pair-stop.patch", "a733-io/patches/pwm-capture-burst.patch"):
        path = src / "hardware" / patch
        if path.exists():  # Older revisions built for rollback predate PWM002.
            copy(path, prefix / "share/armbian-config/pwm" / path.name)
    bridge = src / "hardware/header-gpio"
    if bridge.is_dir():
        for name in ("Makefile", "dkms.conf", "opi_header_gpio.c"):
            copy(bridge/name, root / "usr/src/opi-header-gpio-1.0" / name)
    reload_units(root, init_test_lock=True)


def mesh_files(src, root):
    payload = root / MESH_DIR
    for directory in ("mesh", "reticulum-sx1262", "meshtastic-sx1262"):
        folder = src / "hardware" / directory
        for py in folder.glob("*.py"):
            if not py.name.startswith(("check_", "test_")):
                copy(py, payload / py.name)
        for unit in folder.glob("*.service"):
            copy(unit, root / UNITS / unit.name)
    for name in ("mesh/meshtastic-sim.yaml", "reticulum-sx1262/rnode-interface.conf",
                 "meshtastic-sx1262/zero2w-waveshare.yaml.in"):
        copy(src / "hardware" / name, payload / Path(name).name)
    os.symlink("/opt/armbian-config-zero2w/share/armbian-config/sx1262_spi.py", payload / "sx1262_spi.py")
    copy(src / "hardware/mesh/reticulum.conf", root / "etc/opi-mesh/reticulum.conf")
    write(root / "DEBIAN/conffiles", "/etc/opi-mesh/reticulum.conf\n")
    copy(src / "LICENSE", root / f"usr/share/doc/{MESH}/copyright")
    reload_units(root)
    # Update/downgrade leaves execution and data alone. Stop installed units on removal.
    write(root / "DEBIAN/prerm", """#!/bin/sh
set -eu
if [ "$1" = remove ] && [ -d /run/systemd/system ]; then
    systemctl stop opi-reticulum-radio.service opi-meshtastic-radio.service opi-lxmf.service opi-meshtastic-mail.service opi-meshtastic-sim.service opi-reticulum.service
fi
""", 0o755)


def runtime_files(src, root, inputs, build):
    upstream = build / "native"
    run("dpkg-deb", "--extract", inputs / NATIVE, upstream)
    binary = upstream / "usr/bin/meshtasticd"
    if digest(binary) != "2b37b97948ebd9a75f22d52f653ce4977b6b6be9afdb7c5c02a973bd34e15653":
        raise ValueError("Unexpected native binary")
    copy(binary, root / MESH_DIR / "meshtasticd")
    shutil.copytree(upstream / "usr/share/doc/meshtasticd", root / f"usr/share/doc/{RUNTIME}/meshtasticd", symlinks=True)
    copy(HERE / "inputs.sha256", root / f"usr/share/doc/{RUNTIME}/inputs.sha256")
    runtime = root / MESH_DIR / "venv"
    site = runtime / "lib/python3.14/site-packages"
    wheels = sorted((inputs / "wheels").glob("*.whl"))
    specs = [p.name.split("-")[0] + "==" + p.name.split("-")[1] for p in wheels]
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "--no-index",
           "--no-cache-dir", "--no-deps", "--no-compile", "--only-binary=:all:",
           "--python-version", "3.14", "--implementation", "cp", "--abi", "cp314", "--abi", "abi3",
           "--platform", "manylinux_2_28_aarch64", "--platform", "manylinux2014_aarch64",
           "--target", str(site), "--find-links", str(inputs / "wheels"), *specs]
    run(*pip, stdout=subprocess.DEVNULL)
    (runtime / "bin").mkdir(exist_ok=True)
    for script in (site / "bin").iterdir():
        lines = script.read_bytes().split(b"\n", 1)
        if not lines[0].startswith(b"#!") or len(lines) != 2:
            raise ValueError(f"Unexpected wheel entry point: {script.name}")
        dst = runtime / "bin" / script.name
        dst.write_bytes(b"#!/opt/opi-mesh/venv/bin/python\n" + lines[1])
        dst.chmod(0o755)
        script.unlink()
    (site / "bin").rmdir()
    (runtime / "bin/python").symlink_to("/usr/bin/python3.14")
    write(runtime / "pyvenv.cfg", "home = /usr/bin\ninclude-system-site-packages = true\nversion = 3.14\n")
    fix = src / "hardware/reticulum-sx1262/rns-1.6.1-signal-escape.patch"
    if fix.is_file():
        run("patch", "--batch", "--fuzz=0", "-p1", "-i", fix, cwd=site, stdout=subprocess.DEVNULL)
        decoder = site / "RNS/Interfaces/RNodeInterface.py"
        if digest(decoder) != "1024690fe61c532ce6ac25c9afec2397850355d32bb83caef72441458d0afef9":
            raise ValueError("RNS patch verification failed")
        copy(fix, root / f"usr/share/doc/{RUNTIME}"/fix.name)
    # pip's --target relocates console scripts. Retain correct RECORD entries
    # for them and for the changed RNS source in the final package.
    for record in site.glob("*.dist-info/RECORD"):
        with record.open(newline="") as f:
            rows = list(csv.reader(f))
        for row in rows:
            rel = row[0]
            if "/bin/" in rel and (runtime / "bin" / Path(rel).name).is_file():
                path = runtime / "bin" / Path(rel).name
                row[0] = os.path.relpath(path, site)
            elif fix.is_file() and rel == "RNS/Interfaces/RNodeInterface.py":
                path = site / rel
            else:
                continue
            row[1] = "sha256=" + base64.urlsafe_b64encode(bytes.fromhex(digest(path))).rstrip(b"=").decode()
            row[2] = str(path.stat().st_size)
        with record.open("w", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("revision")
    cli.add_argument("--inputs", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--work", type=Path, required=True, help="Disk-backed scratch parent")
    args = cli.parse_args()
    rev = output("git", "-C", REPO, "rev-parse", "--verify", args.revision + "^{commit}")
    count = output("git", "-C", REPO, "rev-list", "--count", rev)
    version = f"0.1~git{count}.{rev[:8]}"
    epoch = output("git", "-C", REPO, "show", "-s", "--format=%ct", rev)
    env = os.environ | {"SOURCE_DATE_EPOCH": epoch}
    inputs = args.inputs.resolve()
    verify_inputs(inputs)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.work) as tmp:
        build = Path(tmp).resolve()
        src = build / "source"
        src.mkdir()
        archive_source(rev, src)

        core_files(src, build / CORE)
        core_deps = "armbian-config, python3, jq, systemd, util-linux"
        if (src / "share/armbian-config/spi_devices.py").exists():
            core_deps += ", device-tree-compiler"
        if (src / "hardware/h616-io/80-opi-zero2w-uart.rules").exists():
            core_deps += ", udev"
        package(build / CORE, CORE, version, "all", core_deps,
                rev, "Modular Orange Pi Zero 2W Armbian configurator", out, env)

        runtime_files(src, build / RUNTIME, inputs, build)
        native_deps = output("dpkg-deb", "-f", inputs / NATIVE, "Depends")
        runtime_deps = (native_deps + ", python3 (>= 3.14), python3 (<< 3.15), python3-cryptography, "
                        "python3-packaging (>= 24), python3-yaml (>= 6.0.1), python3-urllib3 (>= 1.26), "
                        "python3-libgpiod (>= 2)")
        package(build / RUNTIME, RUNTIME, version, "arm64", runtime_deps,
                rev, "Pinned offline ARM64 Python and Meshtastic runtime for Ubuntu Resolute", out, env)

        mesh_files(src, build / MESH)
        mesh_deps = f"{CORE} (= {version}), {RUNTIME} (= {version}), systemd, iproute2"
        package(build / MESH, MESH, version, "all", mesh_deps,
                rev, "Zero 2W mesh mailboxes, services and sealed radio profiles", out, env)


if __name__ == "__main__":
    main()
