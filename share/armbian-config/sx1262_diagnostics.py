"""Read selector, kernel and worker status without connecting to the radio or RNS."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

import sx1262_spi as spi
from sx1262_mode import HARDWARE, service_states

ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError)
SNAPSHOTS = {"hardware": Path("/run/opi-reticulum-radio/rx.json"),
             "no-radio": Path("/run/opi-sx1262-test-reticulum/rx.json")}


def clean(value):
    # The TUI renders dialog colour escapes. Treat error strings only as data.
    return " ".join("".join(c if c.isprintable() else " " for c in str(value))
                    .replace("\\", "＼").split())[:240]


def read_snapshot(path, unit, now=None):
    if unit["ActiveState"] != "active" or unit["SubState"] != "running":
        raise ValueError("worker " + unit["ActiveState"])
    try:
        with path.open() as stream:
            raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError("oversized worker snapshot")
            data = json.loads(raw)
    except FileNotFoundError:
        raise ValueError("worker has no RX snapshot") from None
    if (data["version"] != 1 or not unit["InvocationID"] or data["invocation"] != unit["InvocationID"]
            or data["pid"] != int(unit["MainPID"])):
        raise ValueError("snapshot belongs to another worker")
    if now is None:
        now = time.monotonic()
    if not 0 <= now - data["updated"] <= 8:
        raise ValueError("stale worker snapshot")
    return data


def rx_lines(data, now):
    counters = ("frames", "packets", "crc", "header_errors", "incomplete", "orphans")
    if any(type(data[k]) is not int or data[k] < 0 for k in counters) or type(data["pending"]) is not bool:
        raise ValueError("invalid worker counters")
    last = data["last"]
    if last is None:
        sample = "RSSI: --    SNR: --    (no complete packet)"
    else:
        rssi, snr, at = last["rssi_dbm"], last["snr_db"], last["at"]
        if not (-127.5 <= rssi <= 0 and -32 <= snr <= 31.75 and 0 <= at <= now):
            raise ValueError("invalid signal sample")
        sample = f"RSSI: {rssi:g} dBm    SNR: {snr:g} dB    ({int(now-at)} s ago)"
    return [f"RNode host: {clean(data['host'])}   Applied SPI: {data['spi_hz']} Hz",
            f"Valid frames: {data['frames']}   Complete packets: {data['packets']}",
            f"CRC errors: {data['crc']}   Header errors: {data['header_errors']}",
            f"Split: {data['incomplete']} abandoned, {data['orphans']} orphan, {int(data['pending'])} pending",
            sample]


def report(selector):
    backend = selector.backend
    lines = [f"Profile: {backend.name}"]
    try:
        saved, pending = selector.read()
        lines[0] += f"   Saved mode: {saved}"
        if pending:
            lines.append(f"Pending: {pending[0]} -> {pending[1]}")
    except ERRORS as e:
        lines.append(f"Saved state: {clean(e)}")
    table = {}
    observed = None
    try:
        table = backend.units_status()
        holder = backend.proc_owner(backend.lock.lstat())
        lines.append(f"Lock PID: {holder or 'free'}")
        observed = backend.resolve_owner(table, holder)
        lines[-1] += f"   Current owner: {observed}"
    except ERRORS as e:
        lines.append(f"Ownership: {clean(e)}")
    try:
        route = spi.discover()
        policy = Path("/etc/systemd/system") / (HARDWARE["reticulum"] + ".d/50-devices.conf")
        bound = policy.is_file() and policy.read_text() == spi.device_policy(route)
        lines.append(f"SPI: {route.spi}   CS0 / PI3 (pin 40)   RNode access: {'configured' if bound else 'sealed'}")
    except ERRORS as e:
        lines.append(f"SPI route: {clean(e)}")
    try:
        cap = spi.ceiling()
        lines.append(f"Mode 0 / 8-bit / MSB first   Next: {spi.selected(cap)} Hz   Max: {cap} Hz")
    except ERRORS as e:
        lines.append(f"SPI clock: {clean(e)}")
    try:
        record = json.loads((selector.directory / f"{backend.name}-last-error.json").read_text())
        stamp = datetime.fromtimestamp(record["time"], timezone.utc).strftime("%m-%d %H:%M UTC")
        lines.append(f"Last switch failure ({stamp}, {clean(record['action'])}): {clean(record['error'])}")
    except FileNotFoundError:
        lines.append("Last switch failure: none recorded")
    except ERRORS as e:
        lines.append(f"Last switch failure: unavailable ({clean(e)})")
    try:
        units = service_states((HARDWARE["reticulum"], "opi-reticulum-rnode-link.service"))
        lines.append(f"Radio service: {units[HARDWARE['reticulum']]['ActiveState']}   "
                     f"RNS attachment service: {units['opi-reticulum-rnode-link.service']['ActiveState']}")
    except ERRORS as e:
        lines.append(f"Radio services: {clean(e)}")
    lines.append("RNode RX / " + ("software double" if backend.name == "no-radio" else "hardware"))
    try:
        unit = table[backend.units["reticulum"]]
        if unit["ActiveState"] == "active" and observed != "reticulum":
            raise ValueError("RNode ownership not confirmed")
        data = read_snapshot(SNAPSHOTS[backend.name], unit)
        lines.extend(rx_lines(data, time.monotonic()))
    except ERRORS as e:
        lines.extend([f"RX counters: unavailable ({clean(e)})", "RSSI: --    SNR: --"])
    return "\n".join(lines)
