#!/usr/bin/env python3
"""Transactional SX1262 owner selection for the Zero 2W configurator."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time

MODES = ("off", "meshtastic", "reticulum", "lorawan")
PROFILE = Path("/etc/armbian-config/sx1262-profile")
STATE = Path("/var/lib/opi-sx1262-mode")
HARDWARE = {
    "meshtastic": "opi-meshtastic-radio.service",
    "reticulum": "opi-reticulum-radio.service",
    "lorawan": "opi-lorawan.service",
}
TEST = {mode: f"opi-sx1262-test@{mode}.service" for mode in HARDWARE}
GUARDS = ("meshtasticd.service", "opi-radio-diagnostics.service")
LOCKS = {"no-radio": "/run/lock/opi-sx1262-test.lock", "hardware": "/run/lock/opi-radio.lock"}


class ModeError(Exception):
    pass


def profile():
    try:
        name = PROFILE.read_text().strip()
    except FileNotFoundError:
        name = "no-radio"
    if name not in LOCKS:
        raise ModeError("Unknown SX1262 profile. Expected no-radio or hardware.")
    return name


def run(*args):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=40)
    if proc.returncode:
        raise ModeError(proc.stderr.strip() or f"{args[0]} exited {proc.returncode}")
    return proc.stdout


class Backends:
    def __init__(self, name):
        self.units = TEST if name == "no-radio" else HARDWARE
        self.guards = () if name == "no-radio" else GUARDS
        self.lock = Path(LOCKS[name])
        self.name = name

    def units_status(self):
        names = (*self.units.values(), *self.guards)
        proc = subprocess.run(["systemctl", "show", "--all", "-p", "Id,LoadState,ActiveState,SubState,MainPID,Job", *names],
                              text=True, capture_output=True, timeout=10)
        table = {}
        for block in proc.stdout.strip().split("\n\n"):
            fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            if all(k in fields for k in ("Id", "LoadState", "ActiveState", "SubState", "MainPID", "Job")):
                table[fields["Id"]] = fields
        if set(table) != set(names) or proc.returncode not in (0, 4):
            raise ModeError("Cannot determine the state of all radio services.")
        return table

    def lock_owner(self):
        # Verify exclusivity against the same inode used by the radio workers.
        fd = os.open(self.lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ModeError(f"Invalid owner lock: {self.lock}")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return None
            except BlockingIOError:
                pass
            key = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
            for line in Path("/proc/locks").read_text().splitlines():
                fields = line.split()
                if fields[1:4] == ["FLOCK", "ADVISORY", "WRITE"]:
                    major, minor, inode = fields[5].split(":")
                    if (int(major, 16), int(minor, 16), int(inode)) == key:
                        return int(fields[4])
            raise ModeError("Owner lock is busy; its exclusive holder could not be identified.")
        finally:
            os.close(fd)

    def current(self):
        table = self.units_status()
        active = []
        for unit, fields in table.items():
            state = fields["ActiveState"]
            if fields["Job"]:
                raise ModeError(f"{unit} has a pending systemd job.")
            if state in ("inactive", "failed"):
                continue
            if unit in self.guards:
                raise ModeError(f"External radio service is {state}: {unit}")
            if state != "active" or fields["SubState"] != "running":
                raise ModeError(f"{unit} is {state}/{fields['SubState']}")
            active.append(unit)
        owner = self.lock_owner()
        if not active and owner is None:
            return "off"
        if len(active) == 1 and owner and owner == int(table[active[0]]["MainPID"]):
            return next(mode for mode, unit in self.units.items() if unit == active[0])
        raise ModeError(f"Radio ownership mismatch: services={active}, lock PID={owner}.")

    def preflight(self, mode):
        if mode == "off":
            return
        unit = self.units[mode]
        if self.units_status()[unit]["LoadState"] != "loaded":
            raise ModeError(f"Backend unavailable: {unit}")
        if self.name == "hardware" and mode == "lorawan":
            for action in ("preflight", "status"):
                run("/usr/local/bin/opi-lorawan", action, "/etc/opi-lorawan/lorawan.conf",
                    "/etc/opi-lorawan/credentials.conf", "/var/lib/opi-lorawan")

    def start(self, mode):
        run("systemctl", "start", self.units[mode])

    def stop(self, mode):
        run("systemctl", "stop", self.units[mode])

    def await_mode(self, mode):
        end = time.monotonic() + 5
        stable = False
        detail = ""
        while time.monotonic() < end:
            try:
                observed = self.current()
                if observed == mode and stable:
                    return
                stable = observed == mode
                detail = f"observed {observed}"
            except ModeError as err:
                stable, detail = False, str(err)
            time.sleep(0.15)
        raise ModeError(f"Health check failed for {mode}: {detail}")


class Selector:
    def __init__(self, backend, directory):
        self.backend = backend
        self.directory = directory
        self.path = directory / f"{backend.name}.json"

    @contextmanager
    def exclusive(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.directory / "transition.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ModeError("Another SX1262 change is in progress.") from None
            yield

    def read(self):
        try:
            state = json.loads(self.path.read_text())
        except FileNotFoundError:
            return "off", None
        if not isinstance(state, dict) or state.get("mode") not in MODES or "pending" not in state:
            raise ModeError("Invalid saved SX1262 state.")
        pending = state["pending"]
        if pending is not None and not (isinstance(pending, list) and len(pending)==2
                                        and all(m in MODES for m in pending) and pending[0]!=pending[1]):
            raise ModeError("Invalid saved SX1262 transition.")
        return state["mode"], pending

    def save(self, mode, pending=None):
        with tempfile.NamedTemporaryFile("w", dir=self.directory, delete=False) as tmp:
            try:
                json.dump(dict(mode=mode, pending=pending), tmp)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
                os.replace(tmp.name, self.path)
                fd = os.open(self.directory, os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def stop_participant(self, mode):
        if mode != "off":
            unit = self.backend.units[mode]
            status = self.backend.units_status()[unit]
            if status["Job"] or status["ActiveState"] not in ("inactive", "failed"):
                self.backend.stop(mode)

    def restore(self, old, attempted):
        # A failed start can still leave a process. Touch only our participants.
        self.stop_participant(attempted)
        if self.backend.current() != old:
            self.backend.await_mode("off")
            if old != "off":
                self.backend.preflight(old)
                self.backend.start(old)
        self.backend.await_mode(old)

    def change(self, target=None):
        with self.exclusive():
            saved, pending = self.read()
            target = saved if target is None else target
            if target not in MODES:
                raise ModeError("Unknown radio mode.")
            if pending:
                if target == "off":
                    # Off must never briefly start a previous transmitter.
                    for mode in reversed(pending):
                        self.stop_participant(mode)
                    self.backend.await_mode("off")
                    self.save("off")
                    return "Interrupted transition cleared. Selected off. Ownership verified."
                self.restore(*pending)
                self.save(saved)
            old = self.backend.current()
            if old == target:
                self.backend.await_mode(target)
                if saved != target:
                    self.save(target)
                return f"Selected {target}. Ownership verified."
            self.backend.preflight(target)
            self.save(saved, [old, target])
            try:
                if old != "off":
                    self.backend.stop(old)
                self.backend.await_mode("off")
                if target != "off":
                    self.backend.start(target)
                    self.backend.await_mode(target)
                self.save(target)
            except (ModeError, OSError, subprocess.SubprocessError) as error:
                try:
                    self.restore(old, target)
                    self.save(saved)
                except (ModeError, OSError, subprocess.SubprocessError) as undo:
                    raise ModeError(f"Switch failed: {error}\nRollback incomplete: {undo}\n"
                                    "Pending transaction retained. Inspect status and retry apply.") from error
                raise ModeError(f"Switch failed: {error}\nRolled back to {old}. Saved mode: {saved}.") from error
            return f"Switched {old} -> {target}. Ownership verified."

    def status(self):
        saved, pending = self.read()
        print(f"Profile: {self.backend.name}\nSaved mode: {saved}")
        if pending:
            print(f"Pending transaction: {pending[0]} -> {pending[1]}")
        print("Current owner:", self.backend.current())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("profile", "status", "apply"):
        sub.add_parser(action)
    sub.add_parser("set").add_argument("mode", choices=MODES)
    args = parser.parse_args()
    name = profile()
    owner = Selector(Backends(name), STATE)
    if args.action == "profile":
        print(name)
    elif args.action == "status":
        owner.status()
    else:
        print(f"Profile: {name}", flush=True)
        print(owner.change(getattr(args, "mode", None)))


if __name__ == "__main__":
    try:
        main()
    except (ModeError, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
