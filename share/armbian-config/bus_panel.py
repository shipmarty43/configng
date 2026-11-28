"""Read-only SPI1 inventory and private candidate boot trees for the Zero 2W panel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from dt_clock_overlay import install_blob, tokens
from spi1_radios import BUS, CLIENTS, SHARED, SINGLE, peer_clocks, select
from spi_devices import MARKER, PARKED, managed, saved_names
from sx1262_spi import selected
from uart_routes import PIO, cells, enabled, env_content, read_tree, rollback_reordered, strings

PROFILES = {"single": "enable", "shared": "shared", "off": "disable"}
LABELS = ("SX1262", "CC1101", "nRF24")
PINS = {(8, 3): (40, "PI3"), (7, 9): (26, "PH9"), (7, 5): (24, "PH5")}
LOCKS = ("opi-radio.lock", "opi-spi1-cs1.lock", "opi-spi1-cs2.lock")


def digest(*parts):
    h = hashlib.sha256()
    for part in parts:
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file: {path.name}")
    return path


def matching_backup(root, before):
    folder = root / "armbianEnv.txt.spi1-panel-backups"
    if folder.is_symlink():
        raise ValueError("Unsafe profile backup directory")
    if not folder.exists():
        return None
    current = env_content(before.read_text())
    entries = (p for p in folder.iterdir() if re.fullmatch(r"change\.[A-Za-z0-9]+", p.name)
               and not p.is_symlink() and p.is_dir())
    for p in sorted(entries, key=lambda entry: entry.stat().st_mtime_ns, reverse=True):
        if not all((p / f).is_file() and not (p / f).is_symlink() for f in ("before", "after")):
            continue
        if env_content((p / "after").read_text()) == current:
            return p
        # A prepared but interrupted rename may precede the last committed entry.
        if env_content((p / "before").read_text()) != current:
            break
    return None


def stage(root, snapshot, work, target):
    # The only symlink in the private tree points to the normal kernel DTB directory.
    if (root / "overlay-user").is_symlink() or any(os.path.lexists(root / n) for n in
            ("fixup.scr", "overlay-user/user-fixup.scr", "extlinux/extlinux.conf")):
        raise ValueError("Unsupported custom boot route")
    before = work / "before"
    shutil.copyfile(regular(snapshot), before)
    shadow = work / "boot"
    shadow.mkdir()
    shutil.copyfile(root / "boot.scr", shadow / "boot.scr")
    (shadow / "dtb").symlink_to((root / "dtb").resolve(strict=True))
    shutil.copyfile(before, shadow / "armbianEnv.txt")
    folder = shadow / "overlay-user"
    folder.mkdir()
    try:
        backup = matching_backup(root, before)
    except PermissionError:
        if target == "undo":
            raise
        backup = None
    after = work / "after"
    if backup:
        backup_before = regular(backup / "before")
        (work / "undo-key").write_text(digest(backup.name.encode(), backup_before.read_bytes(),
                                              regular(backup / "after").read_bytes()))
    if target == "undo":
        if not backup:
            raise ValueError("No matching profile change to undo")
        rollback_reordered(backup_before, backup / "after", before, after,
                           allowed=("user_overlays", PARKED))
        if before.read_bytes() == (backup / "after").read_bytes():
            shutil.copyfile(backup_before, after)  # Also restore exact ordering/newlines.
    names = set()
    for env in (before, after) if after.exists() else (before,):
        text = env.read_text()
        env_content(text)
        names.update(tokens(text) + saved_names(text))
    provider = {"single": SINGLE, "shared": SHARED}.get(target)
    if provider and os.path.lexists(root / "overlay-user" / (provider + ".dtbo")):
        names.add(provider)
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError("Invalid overlay name")
        src = regular(root / "overlay-user" / (name + ".dtbo"))
        shutil.copyfile(src, folder / src.name)
    peer_clocks(saved_names(before.read_text()), folder, parked=True)
    if target in PROFILES:
        select(before, after, folder, PROFILES[target])
    elif target == "state":
        shutil.copyfile(before, after)
    peer_clocks(saved_names(after.read_text()), folder, parked=True)


def publish(root, work):
    # All other immutable inputs were copied from /boot. Only a profile provider
    # can be generated during preview. Commit this dependency before the env rename.
    active = tokens((work / "after").read_text())
    for provider in (SINGLE, SHARED):
        if provider in active:
            data = (work / "boot/overlay-user" / (provider + ".dtbo")).read_bytes()
            install_blob(root / "overlay-user", provider, data)


def lock_owner(path):
    try:
        st = path.stat()
        for line in Path("/proc/locks").read_text().splitlines():
            fields = line.split()
            if len(fields) < 6 or fields[1] != "FLOCK":
                continue
            major, minor, inode = fields[5].split(":")
            if (int(major, 16), int(minor, 16), int(inode)) == (
                    os.major(st.st_dev), os.minor(st.st_dev), st.st_ino):
                return f"PID {fields[4]}"
        return "свободна"
    except (OSError, ValueError):
        return "неизвестно"


def live_tree(dt):
    # Only read the DT nodes needed for the inventory. No /dev descriptors.
    paths = ["/", "/soc", PIO, BUS]
    ctrl = dt / BUS.lstrip("/")
    if ctrl.is_dir():
        paths.extend(f"{BUS}/{p.name}" for p in ctrl.iterdir() if p.is_dir())
    tree = {}
    props = ("status", "reg", "compatible", "phandle", "cs-gpios", "spi-max-frequency", MARKER)
    for path in paths:
        node = dt / path.lstrip("/")
        if node.is_dir():
            tree[path] = {k: (node / k).read_bytes() for k in props if (node / k).is_file()}
    return tree


def inventory(tree, dt=None, devices=None, locks=None):
    if BUS not in tree:
        return {"profile": "unknown", "rows": []}
    bus_on = enabled(tree, BUS)
    selects = cells(tree[BUS].get("cs-gpios", b""))
    pio = cells(tree.get(PIO, {}).get("phandle", b""))
    active = {p for p, props in tree.items() if p.rpartition("/")[0] == BUS
              and "reg" in props and bus_on and enabled(tree, p)}
    rows = []
    for cs, (child, compat, _) in enumerate(CLIENTS):
        path = f"{BUS}/{child}"
        props = tree.get(path, {})
        if path not in active or compat not in strings(props.get("compatible", b"")) or cells(props["reg"]) != [cs]:
            continue
        ceiling, = cells(props["spi-max-frequency"])
        request = selected(ceiling) if cs == 0 else (
            cells(props[MARKER])[0] if MARKER in props else min(500_000, ceiling))
        spec = selects[4 * cs:4 * cs + 4]
        pin, pad = (PINS.get(tuple(spec[1:3]), (None, None)) if
                    len(spec) == 4 and spec[:1] == pio and spec[3] == 1 else (None, None))
        row = dict(cs=cs, device=LABELS[cs], pin=pin, pad=pad, requested_hz=request, ceiling_hz=ceiling)
        if dt is not None:
            node = dt / path.lstrip("/")
            paths = ["/dev/" + dev.name for dev in devices.glob(f"spidev*.{cs}")
                     if re.fullmatch(r"spidev\d+\.\d+", dev.name)
                     and (dev / "device/of_node").resolve() == node.resolve()]
            row.update(endpoint=paths[0] if len(paths) == 1 else None, lock=lock_owner(locks / LOCKS[cs]))
        rows.append(row)
    profile = "external" if bus_on else "off"
    if len(rows) == len(active):
        if [r["cs"] for r in rows] == [0, 1, 2]:
            profile = "shared"
        elif [r["cs"] for r in rows] == [0]:
            profile = "single"
    return {"profile": profile, "rows": rows}


def describe(work, target, dt, devices, locks):
    states = []
    for name in ("before", "after"):
        env = (work / name).read_text()
        state = inventory(read_tree(work / (name + ".dtb")))
        state["parked"] = {str(cs): hz for (_, cs), (_, hz) in managed(saved_names(env)).items()}
        states.append(state)
    current, candidate = states
    revision = digest((work / "before").read_bytes(), (work / "before.dtb").read_bytes(),
                      json.dumps(current, sort_keys=True).encode())
    undo = work / "undo-key"
    undo_token = digest(revision.encode(), undo.read_bytes()) if undo.is_file() else None
    token = digest(revision.encode(), target.encode(), (work / "after").read_bytes(),
                   (work / "after.dtb").read_bytes(), json.dumps(candidate, sort_keys=True).encode())
    return dict(live=inventory(live_tree(dt), dt, devices, locks), current=current,
                candidate=candidate, changed=(work / "before").read_bytes() != (work / "after").read_bytes(),
                token=token, undo=undo_token)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="op", required=True)
    for cmd, args in (("stage", "root snapshot work target"), ("describe", "work target dt devices locks"),
                      ("publish", "root work")):
        group = sub.add_parser(cmd)
        for arg in args.split():
            group.add_argument(arg, type=str if arg == "target" else Path)
    kwargs = vars(parser.parse_args())
    op = kwargs.pop("op")
    if op == "describe":
        print(json.dumps(describe(**kwargs), ensure_ascii=False))
    elif op == "stage":
        stage(**kwargs)
    else:
        publish(**kwargs)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
