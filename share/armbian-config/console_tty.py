#!/usr/bin/env python3
"""Select the Linux console on Armbian's Zero 2W U-Boot script route."""
import argparse
import contextlib
import fcntl
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile
import zlib

BOOT = Path("/boot")
SYS = Path("/sys")
DEV = Path("/dev")
ENVFILE = "armbianEnv.txt"
KEYS = ("console", "consoleargs")
SERIAL = re.compile(r"ttyS(?:0|[1-9][0-9]*)")
VT = re.compile(r"tty[1-6]")
MASK = "systemd.mask=serial-getty@"
CUSTOM = "custom"


def supported_boot(boot):
    if (boot / "extlinux/extlinux.conf").exists():
        raise ValueError("An extlinux configuration is present; cannot verify the active boot route.")
    image = (boot / "boot.scr").read_bytes()
    # Legacy U-Boot script image followed by a single length-prefixed component.
    if (len(image) < 72 or image[:4] != bytes.fromhex("27051956") or image[30:32] != b"\x06\x00"
            or struct.unpack_from(">I", image, 12)[0] != len(image)-64
            or zlib.crc32(image[:4] + bytes(4) + image[8:64]) != struct.unpack_from(">I", image, 4)[0]
            or zlib.crc32(image[64:]) != struct.unpack_from(">I", image, 24)[0]
            or struct.unpack_from(">II", image, 64) != (len(image)-72, 0)):
        raise ValueError("Unrecognized or damaged U-Boot script image.")
    lines = image[72:].decode().splitlines()
    rules = {}
    imported = consumes = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            continue
        if line.startswith("env import -t "):
            imported = True
        if "setenv consoleargs " in line:
            if not imported:
                raise ValueError("Unexpected consoleargs before boot environment import.")
            if line in ('setenv consoleargs "splash plymouth.ignore-serial-consoles ${consoleargs}"',
                        'setenv consoleargs "splash=verbose ${consoleargs}"'):
                continue
            match = re.fullmatch(r'if (.+); then setenv consoleargs "([^"]+)"; fi', line)
            if not match:
                raise ValueError("Unsupported consoleargs rule in boot.scr.")
            for term in match[1].split(" || "):
                cond = re.fullmatch(r'test "\$\{console\}" = "(both|display|serial)"', term)
                if not cond or cond[1] in rules:
                    raise ValueError("Unsupported console selector in boot.scr.")
                rules[cond[1]] = match[2]
        if line.startswith('setenv bootargs "') and '${consoleargs}' in line:
            consumes = imported and bool(rules)
    if not consumes or not any("armbianEnv.txt" in line and "load " in line for line in lines):
        raise ValueError("Boot script does not import the expected Armbian console settings.")
    return rules


def values(text):
    result = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in (*KEYS, "extraargs", "extraboardargs"):
            if key in result:
                raise ValueError(f"Duplicate {key} in boot environment.")
            result[key] = value
    return result


def replace_keys(text, new):
    pending = dict(new)
    lines = []
    for line in text.splitlines(keepends=True):
        key, sep, _ = line.partition("=")
        if sep and key in KEYS:
            if key in pending:
                lines.append(f"{key}={pending.pop(key)}\n")
        else:
            lines.append(line)
    output = "".join(lines)
    if pending and output and not output.endswith("\n"):
        output += "\n"
    return output + "".join(f"{k}={v}\n" for k, v in pending.items())


def selection(env, rules):
    mode = env.get("console", "both")
    args = env.get("consoleargs", "") if mode == CUSTOM else rules.get(mode)
    if args is None:
        raise ValueError(f"Unsupported existing console mode: {mode}")
    consoles, masks = [], set()
    for token in args.split():
        m = re.fullmatch(r"console=(tty[0-9]+|ttyS[0-9]+)(?:,[0-9]+[neo]?[78]?)?", token)
        if m:
            consoles.append(m[1])
        elif token.startswith(MASK) and token.endswith(".service") and SERIAL.fullmatch(token[len(MASK):-8]):
            masks.add(token[len(MASK):-8])
        else:
            raise ValueError(f"Unrecognized existing console option: {token}")
    return consoles, masks


def devices():
    result = {}
    for dev in sorted((SYS / "class/tty").glob("tty*")):
        name = dev.name
        if not (DEV / name).is_char_device():
            continue
        if VT.fullmatch(name):
            result[name] = f"Local display VT {name[3:]}"
        elif SERIAL.fullmatch(name):
            node = dev / "device/of_node"
            if (dev / "device/driver").is_dir() and node.is_dir():
                status = node / "status"
                if not status.exists() or status.read_bytes().rstrip(b"\0") in (b"ok", b"okay"):
                    result[name] = f"UART {node.resolve().name}, 115200 baud"
    return result


def targets():
    result = devices()
    if "tty1" in result:
        for tty in list(result):
            if SERIAL.fullmatch(tty):
                result[f"{tty}+tty1"] = f"{tty} at 115200 baud and local display tty1"
    return result


def serial_users(name):
    # A newly selected UART may already be owned by a userspace peripheral.
    ports = str(DEV / name)
    for folder in Path("/proc").glob("[0-9]*/fd"):
        for descriptor in folder.glob("*"):
            try:
                if os.readlink(descriptor) == ports:
                    yield folder.parent.name
                    break
            except FileNotFoundError:
                continue


def plan(text, target, rules):
    env = values(text)
    for key in ("extraargs", "extraboardargs"):
        if any(re.match(r"(?:console|earlycon|earlyprintk|kgdboc)(?:=|$)", t)
               for t in env.get(key, "").split()):
            raise ValueError(f"{key} also configures a console. Reconcile it before switching.")
    old, masks = selection(env, rules)
    requested = target.split("+")
    if target not in targets():
        raise ValueError("Requested TTY is unavailable. See module_console_tty list.")
    for tty in requested:
        if SERIAL.fullmatch(tty) and tty not in old:
            pids = list(serial_users(tty))
            if pids:
                raise ValueError(f"{tty} is open by PID(s) {', '.join(pids)}. Release it first.")
    masks.update(t for t in old if SERIAL.fullmatch(t))
    masks.difference_update(requested)
    args = [f"console={t},115200" if SERIAL.fullmatch(t) else f"console={t}" for t in requested]
    args += [f"{MASK}{t}.service" for t in sorted(masks)]
    return replace_keys(text, {"console": CUSTOM, "consoleargs": " ".join(args)})


def fsync_dir(path):
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def snapshot(file, data):
    with file.open("x", encoding="utf-8", newline="") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def change(boot, action, argument):
    conf = boot / ENVFILE
    store = boot / (ENVFILE + ".tty-backups")
    lock = os.open(str(conf) + ".overlay.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, "r+") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX)
        if conf.is_symlink() or not conf.is_file() or store.is_symlink():
            raise ValueError("Unsafe boot configuration path.")
        before = conf.read_bytes().decode()
        if action == "set":
            after = plan(before, argument, supported_boot(boot))
        else:
            if not re.fullmatch(r"change\.[a-zA-Z0-9_-]+", argument):
                raise ValueError("Invalid backup ID.")
            src = store / argument
            if src.is_symlink() or any((src / name).is_symlink() for name in ("before", "after")):
                raise ValueError("Invalid backup path.")
            current = values(before)
            expected = values((src / "after").read_bytes().decode())
            if any(current.get(k) != expected.get(k) for k in KEYS):
                raise ValueError("Console settings changed since that backup.")
            previous = values((src / "before").read_bytes().decode())
            after = replace_keys(before, {k: previous[k] for k in KEYS if k in previous})
        if before == after:
            print("Console settings already match.")
            return
        store.mkdir(mode=0o700, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix="change.", dir=store))
        snapshot(backup / "before", before)
        snapshot(backup / "after", after)
        fsync_dir(backup)
        fsync_dir(store)
        info = conf.stat()
        fd, temp = tempfile.mkstemp(prefix=".console-tty.", dir=boot)
        try:
            with os.fdopen(fd, "wb") as out:
                os.fchown(out.fileno(), info.st_uid, info.st_gid)
                os.fchmod(out.fileno(), stat.S_IMODE(info.st_mode))
                out.write(after.encode())
                out.flush()
                os.fsync(out.fileno())
            if conf.read_bytes() != before.encode():
                raise ValueError("Boot environment changed concurrently.")
            os.replace(temp, conf)
            fsync_dir(boot)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp)
        print(f"Saved for next boot. Backup: {backup.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for cmd in ("list", "status", "backups"):
        sub.add_parser(cmd)
    sub.add_parser("set").add_argument("target")
    sub.add_parser("rollback").add_argument("backup")
    args = parser.parse_args()
    compat = (SYS / "firmware/devicetree/base/compatible").read_bytes().split(b"\0")
    if b"xunlong,orangepi-zero2w" not in compat or b"allwinner,sun50i-h618" not in compat:
        raise ValueError("Expected Orange Pi Zero 2W.")
    if args.action == "list":
        for name, label in targets().items():
            print(f"{name}\t{label}")
    elif args.action == "backups":
        for path in sorted((BOOT / (ENVFILE + ".tty-backups")).glob("change.*"), reverse=True):
            if (path / "after").is_file():
                print(path.name)
    elif args.action == "status":
        print("Active Linux consoles:", (SYS / "class/tty/console/active").read_text().strip())
        env = values((BOOT / ENVFILE).read_text())
        next_ttys, masks = selection(env, supported_boot(BOOT))
        for tty in devices():
            if SERIAL.fullmatch(tty):
                unit = f"serial-getty@{tty}.service"
                state = subprocess.run(["systemctl", "is-active", unit], text=True, stdout=subprocess.PIPE)
                print(f"Current {unit}: {state.stdout.strip()}")
        print("Next boot consoles:", " ".join(next_ttys))
        print("Serial login masked at next boot:", " ".join(sorted(masks)) or "none")
    else:
        if args.action == "set" and not Path("/usr/lib/systemd/system-generators/systemd-debug-generator").is_file():
            raise ValueError("Missing systemd generator for serial login masking.")
        change(BOOT, args.action, args.target if args.action == "set" else args.backup)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(f"Console TTY: {error}")
