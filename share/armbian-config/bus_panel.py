"""Live header inventory and private candidate boot trees for BUS002."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import a733_panel
import header_panel as header
import uart_routes as uart
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


def matching_backup(root, before, board):
    journal = "a733-panel" if board == "a733" else "spi1-panel"
    folder = root / f"armbianEnv.txt.{journal}-backups"
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


def stage(root, snapshot, work, target, board):
    # The only symlink in the private tree points to the normal kernel DTB directory.
    if (root / "overlay-user").is_symlink() or any(os.path.lexists(root / n) for n in
            ("fixup.scr", "overlay-user/user-fixup.scr", "extlinux/extlinux.conf")):
        raise ValueError("Unsupported custom boot route")
    route = release = None
    if target not in ("state", "undo"):
        if board == "a733":
            route, release = a733_panel.selection(target)
        else:
            route = header.ROUTES.get(target)
            if not route and target not in PROFILES:
                raise ValueError("INVALID: Неизвестный маршрут гребёнки")
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
        backup = matching_backup(root, before, board)
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
                           allowed=("overlays", "user_overlays", PARKED) if board == "h618" else ("overlays", "user_overlays"))
        if before.read_bytes() == (backup / "after").read_bytes():
            shutil.copyfile(backup_before, after)  # Also restore exact ordering/newlines.
    names = set()
    for env in (before, after) if after.exists() else (before,):
        text = env.read_text()
        env_content(text)
        names.update(tokens(text))
        if board == "h618":
            names.update(saved_names(text))
    if board == "a733":
        providers = [step.provider for step in (release, route) if step]
    elif route and route.group == "UART" and route.mode not in ("off", "txrx-ph"):
        providers = [uart.token(route.port, route.mode)]
    else:
        providers = [{"single": SINGLE, "shared": SHARED}.get(target)]
    for provider in providers:
        if provider and os.path.lexists(root / "overlay-user" / (provider + ".dtbo")):
            names.add(provider)
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ValueError("Invalid overlay name")
        src = regular(root / "overlay-user" / (name + ".dtbo"))
        shutil.copyfile(src, folder / src.name)
    if board == "a733":
        if route:
            seed = before
            if release:
                seed = work / "released.env"
                a733_panel.edit(release, before, seed, folder)
            a733_panel.edit(route, seed, work / "base.env", folder, strip=True)
            a733_panel.edit(route, seed, after, folder)
        elif target == "state":
            shutil.copyfile(before, after)
        return
    peer_clocks(saved_names(before.read_text()), folder, parked=True)
    if target in PROFILES:
        select(before, after, folder, PROFILES[target])
    elif route:
        header.edit(header.ROUTES[route.port + "-off"], before, work / "base.env", folder)
        header.edit(route, before, after, folder)
    elif target == "state":
        shutil.copyfile(before, after)
    peer_clocks(saved_names(after.read_text()), folder, parked=True)


def publish(root, work, board):
    active = tokens((work / "after").read_text())
    if board == "a733":
        providers = {r.provider for r in a733_panel.ROUTES.values() if r.provider}
    else:
        providers = {SINGLE, SHARED} | {uart.token(r.port, r.mode) for r in header.ROUTES.values()
                                       if r.group == "UART" and r.mode not in ("off", "txrx-ph")}
    for provider in providers.intersection(active):
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
    # Read the live OF tree, including non-bus consumers such as GPIO keys.
    # Skip firmware payloads, __symbols__ and other unrelated binary properties.
    props = {"status", "reg", "compatible", "phandle", "spi-max-frequency", MARKER,
             "pins", "allwinner,pins", "function", "allwinner,function", "gpio", "gpios",
             "interrupts", "interrupts-extended", "interrupt-parent", "#interrupt-cells",
             "gpio-hog", "spi-cpha", "spi-cpol", "num-cs", "#gpio-cells", "bt_rst_n", "bt_wake", "wlan_regon", uart.DE_PROP}
    tree = {}
    for directory, children, files in os.walk(dt):
        node = Path(directory)
        children[:] = [c for c in children if not c.startswith("__")]
        path = "/" if node == dt else "/" + node.relative_to(dt).as_posix()
        tree[path] = {name: (node / name).read_bytes() for name in files if name in props
                      or name.startswith("pinctrl-")
                      or name.endswith(("-gpios", "-gpio", "_gpio", "_gpios", "_hostwake", "_pwdn"))}
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


def describe(work, target, dt, devices, locks, board):
    states, trees = [], []
    for name in ("before", "after"):
        env = (work / name).read_text()
        tree = read_tree(work / (name + ".dtb"))
        trees.append(tree)
        if board == "a733":
            states.append(a733_panel.inventory(tree))
            continue
        state = inventory(tree)
        state["pins"] = header.pins(tree)
        state["parked"] = {str(cs): hz for (_, cs), (_, hz) in managed(saved_names(env)).items()}
        states.append(state)
    current, candidate = states
    changed = (work / "before").read_bytes() != (work / "after").read_bytes()
    revision = digest((work / "before").read_bytes(), (work / "before.dtb").read_bytes(),
                      json.dumps(current, sort_keys=True).encode())
    undo = work / "undo-key"
    undo_token = digest(revision.encode(), undo.read_bytes()) if undo.is_file() else None
    token = digest(revision.encode(), target.encode(), (work / "after").read_bytes(),
                   (work / "after.dtb").read_bytes(), json.dumps(candidate, sort_keys=True).encode())
    live = live_tree(dt)
    if board == "a733":
        live_state = a733_panel.inventory(live, dt, devices)
    else:
        live_state = inventory(live, dt, devices, locks)
        live_state["pins"] = header.pins(live)
    live_state["gpio_known"] = header.gpio_consumers(live_state["pins"], dt, board=board)
    changed_pins = header.changes(current["pins"], candidate["pins"])
    affected = {row["pin"] for row in changed_pins}
    warnings = [f"Вывод {r['pin']} ({r['pad']}) сейчас удерживает GPIO-клиент {r['gpio_consumer']}."
                for r in live_state["pins"] if r["pin"] in affected and r.get("gpio_consumer")]
    alternative = transition = None
    if board == "a733":
        issues = a733_panel.conflicts(candidate["pins"])
        try:
            a733_panel.validate_stock_pwm(trees[1], (work/"after").read_text())
            if target not in ("state", "undo"):
                route, release = a733_panel.selection(target)
                issues.extend(a733_panel.route_issues(route, read_tree(work / "base.dtb"), *trees))
                if release:
                    transition = a733_panel.transition_label(route, release)
                    if changed and release.path not in a733_panel.owners_on_route(route, current["pins"], candidate["pins"]):
                        issues.append("Выбранный владелец не занимает выводы запрошенного маршрута.")
                    if enabled(trees[1], release.path):
                        issues.append(f"Итоговый DTB не освободил {release.path}.")
                    issues.extend(a733_panel.route_issues(release, trees[1], *trees))
                elif issues:
                    alternative = a733_panel.alternative(target, route, current["pins"], candidate["pins"])
        except (ValueError, KeyError) as exc:
            issues.append(str(exc))
    else:
        issues = header.conflict_messages(candidate["pins"])
    if board == "h618" and target in header.ROUTES:
        issues.extend(header.route_issues(header.ROUTES[target], read_tree(work / "base.dtb"), *trees))
    failure = work / "validation-error"
    if failure.exists() and not issues:
        issues.append(failure.read_text().strip() or "Проверка DTB отклонила конфигурацию.")
    return dict(board="Zero 3W" if board == "a733" else "Zero 2W", live=live_state, current=current, candidate=candidate,
                changed=changed,
                changes=changed_pins, warnings=warnings, issues=issues, alternative=alternative, transition=transition,
                choices=a733_panel.choices() if board == "a733" else header.choices(), token=None if issues else token, undo=undo_token)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", choices=("a733", "h618"), default="h618")
    sub = parser.add_subparsers(dest="op", required=True)
    for cmd, args in (("stage", "root snapshot work target"), ("describe", "work target dt devices locks"),
                      ("publish", "root work")):
        group = sub.add_parser(cmd)
        for arg in args.split():
            group.add_argument(arg, type=str if arg == "target" else Path)
    cmd = sub.add_parser("a733-trees")
    cmd.add_argument("work", type=Path)
    kwargs = vars(parser.parse_args())
    op = kwargs.pop("op")
    if op == "a733-trees":
        a733_panel.compose(kwargs["work"])
    elif op == "describe":
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
