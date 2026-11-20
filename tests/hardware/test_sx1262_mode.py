"""The selector's transaction tests use in-memory workers and a real state directory."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/armbian-config"))
from sx1262_mode import Backends, GUARDS, HARDWARE, ModeError, Selector, TEST


class Workers:
    name = "no-radio"
    units = TEST

    def __init__(self):
        self.active = "off"
        self.unavailable = set()
        self.fail = set()
        self.unhealthy = set()
        self.calls = []
        self.crash = None

    def current(self):
        if self.active in self.unhealthy:
            raise ModeError("Missing owner lock")
        return self.active

    def units_status(self):
        return {unit: {"ActiveState": "active" if m == self.active else "inactive", "Job": ""}
                for m, unit in self.units.items()}

    def preflight(self, mode):
        if mode in self.unavailable:
            raise ModeError("Unavailable")

    def await_mode(self, mode):
        if self.current() != mode:
            raise ModeError("Unexpected owner")

    def start(self, mode):
        self.calls.append(("start", mode))
        if self.active != "off":
            raise AssertionError("Two simultaneous owners")
        if mode in self.fail:
            raise ModeError("Start failure")
        self.active = mode
        if mode == self.crash:
            raise KeyboardInterrupt

    def stop(self, mode):
        self.calls.append(("stop", mode))
        if self.active != mode:
            raise AssertionError("Attempt to stop another owner")
        self.active = "off"


class Transaction(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workers = Workers()
        self.s = Selector(self.workers, Path(tmp.name))

    def test_transitions_and_idempotence(self):
        for mode in ("meshtastic", "reticulum", "lorawan", "off"):
            self.s.change(mode)
            self.assertEqual(self.s.read(), (mode, None))
            calls = self.workers.calls.copy()
            self.s.change(mode)
            self.assertEqual(self.workers.calls, calls)
        self.assertEqual(self.workers.active, "off")

    def test_preflight_keeps_previous_process(self):
        self.s.change("meshtastic")
        self.workers.unavailable.add("reticulum")
        with self.assertRaisesRegex(ModeError, "Unavailable"):
            self.s.change("reticulum")
        self.assertEqual(self.workers.calls, [("start", "meshtastic")])
        self.assertEqual(self.s.read(), ("meshtastic", None))

    def test_start_failure_with_previous_off(self):
        self.workers.fail.add("reticulum")
        with self.assertRaisesRegex(ModeError, "Rolled back to off"):
            self.s.change("reticulum")
        self.assertEqual(self.s.read(), ("off", None))

    def test_started_but_unhealthy(self):
        self.s.change("meshtastic")
        self.workers.unhealthy.add("lorawan")
        with self.assertRaisesRegex(ModeError, "Rolled back to meshtastic"):
            self.s.change("lorawan")
        self.assertEqual(self.workers.calls[-2:], [("stop","lorawan"), ("start","meshtastic")])
        self.assertEqual(self.s.read(), ("meshtastic", None))

    def test_failed_rollback_and_retry(self):
        self.s.change("lorawan")
        self.workers.fail.update(("reticulum", "lorawan"))
        with self.assertRaisesRegex(ModeError, "Rollback incomplete"):
            self.s.change("reticulum")
        self.assertEqual(self.s.read(), ("lorawan", ["lorawan", "reticulum"]))
        self.workers.fail.clear()
        self.s.change()
        self.assertEqual(self.workers.active, "lorawan")
        self.assertEqual(self.s.read(), ("lorawan", None))

    def test_interruption_after_start_and_apply_on_boot(self):
        self.s.change("meshtastic")
        self.workers.crash = "reticulum"
        with self.assertRaises(KeyboardInterrupt):
            self.s.change("reticulum")
        self.assertEqual(self.s.read(), ("meshtastic", ["meshtastic", "reticulum"]))
        self.s.change()
        self.assertEqual(self.workers.active, "meshtastic")
        self.workers.active = "off"
        self.s.change()
        self.assertEqual(self.workers.calls[-1], ("start", "meshtastic"))

    def test_invalid_state_or_simultaneous_change(self):
        with self.s.exclusive(), self.assertRaisesRegex(ModeError, "in progress"):
            self.s.change("meshtastic")
        self.s.path.write_text('{"mode":"invalid","pending":null}')
        with self.assertRaisesRegex(ModeError, "Invalid saved"):
            self.s.change("reticulum")
        self.assertEqual(self.workers.calls, [])

    def test_off_never_restarts_previous_owner_during_recovery(self):
        self.s.change("meshtastic")
        self.workers.crash = "reticulum"
        with self.assertRaises(KeyboardInterrupt):
            self.s.change("reticulum")
        self.workers.calls.clear()
        self.s.change("off")
        self.assertEqual(self.workers.calls, [("stop", "reticulum")])
        self.assertEqual(self.s.read(), ("off", None))

    def test_commit_failure_restores_actual_owner(self):
        self.s.change("lorawan")
        save = self.s.save
        def fail_commit(mode, pending=None):
            if mode == "reticulum" and pending is None:
                raise OSError("Injected write failure")
            save(mode, pending)
        with patch.object(self.s, "save", side_effect=fail_commit), self.assertRaisesRegex(ModeError, "Rolled back"):
            self.s.change("reticulum")
        self.assertEqual(self.workers.active, "lorawan")
        self.assertEqual(self.s.read(), ("lorawan", None))


class HardwareContract(unittest.TestCase):
    def test_meshtastic_handoff_checks_hardware_gate_only_for_live_profile(self):
        for profile in ("no-radio", "hardware"):
            backend = Backends(profile)
            table = {backend.units["meshtastic"]: {"LoadState": "loaded"}}
            with patch.object(backend, "units_status", return_value=table), patch("sx1262_mode.meshtastic_profile") as check:
                backend.preflight("meshtastic")
                if profile == "hardware":
                    check.assert_called_once_with("preflight")
                else:
                    check.assert_not_called()

    def test_kernel_owner_and_unmanaged_services(self):
        backend = Backends("hardware")
        idle = dict(LoadState="loaded", ActiveState="inactive", SubState="dead", MainPID="0", Job="")
        running = idle | dict(ActiveState="active", SubState="running", MainPID="77")
        table = {unit: idle.copy() for unit in (*HARDWARE.values(), *GUARDS)}
        table[HARDWARE["meshtastic"]] = running
        with patch.object(backend, "units_status", return_value=table):
            with patch.object(backend, "lock_owner", return_value=77):
                self.assertEqual(backend.current(), "meshtastic")
                table[GUARDS[0]]["Job"] = "100"
                with self.assertRaisesRegex(ModeError, "pending"):
                    backend.current()
                table[GUARDS[0]] = running
                with self.assertRaisesRegex(ModeError, "External"):
                    backend.current()
            table[GUARDS[0]] = idle
            with patch.object(backend, "lock_owner", return_value=80), self.assertRaisesRegex(ModeError, "mismatch"):
                backend.current()

    def test_reticulum_preflight_only_on_hardware(self):
        for profile in ("no-radio", "hardware"):
            backend = Backends(profile)
            with patch.object(backend, "units_status", return_value={backend.units["reticulum"]: {"LoadState": "loaded"}}), \
                    patch("sx1262_mode.reticulum_profile") as check:
                backend.preflight("reticulum")
                if profile == "hardware":
                    check.assert_called_once_with("preflight")
                else:
                    check.assert_not_called()

    def test_lorawan_preflight_and_saved_state_check(self):
        backend = Backends("hardware")
        table = {HARDWARE["lorawan"]: {"LoadState": "loaded"}}
        with patch.object(backend, "units_status", return_value=table), patch("sx1262_spi.ceiling", return_value=2000000), patch("sx1262_mode.run") as call:
            backend.preflight("lorawan")
        self.assertEqual([c.args[1] for c in call.call_args_list], ["preflight", "status"])


if __name__ == "__main__":
    unittest.main()
