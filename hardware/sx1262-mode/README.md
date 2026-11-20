# SX1262 mode selector

Open **System → Hardware → SX1262 mode** (`sudo armbian-config-zero2w --cmd SXMD01` on the test board). Choose **Off**, **Meshtastic**, **Reticulum** or **LoRaWAN**. **Status** shows the profile, saved selection, live owner and any unfinished transaction. The menu is independent of the Meshtastic simulator, Reticulum TCP, messaging and GNSS services.

```sh
sudo armbian-config-zero2w --api module_sx1262_mode status
sudo armbian-config-zero2w --api module_sx1262_mode set meshtastic
sudo armbian-config-zero2w --api module_sx1262_mode set off
sudo armbian-config-zero2w --api module_sx1262_mode apply
```

## Profiles

The root-owned file `/etc/armbian-config/sx1262-profile` selects the installation profile. A missing file defaults to `no-radio`. An unrecognized value aborts the operation. Each profile has its own committed state and owner lock.

| Selection | `no-radio` profile | `hardware` profile |
|---|---|---|
| Off | All test workers stopped | All managed radio workers stopped |
| Meshtastic | `opi-sx1262-test@meshtastic.service` | `opi-meshtastic-radio.service` |
| Reticulum | `opi-sx1262-test@reticulum.service` | `opi-reticulum-radio.service` |
| LoRaWAN | `opi-sx1262-test@lorawan.service` | `opi-lorawan.service` |

The no-radio workers are independent systemd instances. Each runs `flock --no-fork` and sleeps with an exclusive lock on `/run/lock/opi-sx1262-test.lock`. They have private devices and networks, an empty capability set and a 16 MiB memory limit. Selecting a protocol here exercises ownership handoff. The protocol software itself runs in separate integration tests.

The hardware mapping is for separately installed, qualified radio services. The [Waveshare Meshtastic backend](../meshtastic-sx1262/README.md) is available in sealed preparation mode. The Reticulum SPI adapter remains to be supplied. A participating worker must obtain `/run/lock/opi-radio.lock` **before hardware access**, hold it through hardware cleanup, and have the lock attributed to its systemd MainPID. The existing LoRaWAN worker implements this contract. Its configuration, wiring qualification flag and saved LoRaWAN state are checked before a handoff to it. A conventional `meshtasticd.service` or an active radio diagnostic is treated as an external owner. Uncooperative processes that bypass the shared lock are outside the selector's control. Radio transmission can begin when a hardware worker starts.

## Install the no-radio profile

Use a built configurator from this fork. The package manifest includes the helper, both systemd units and the tmpfiles rule. For a package installation, run `sudo systemd-tmpfiles --create opi-sx1262-test.conf` and `sudo systemctl enable --now opi-sx1262-restore.service`. For a fresh installation from the checkout:

```sh
sudo install -d /etc/armbian-config /usr/local/lib/systemd/system /usr/local/lib/tmpfiles.d
printf '%s\n' no-radio | sudo tee /etc/armbian-config/sx1262-profile
sudo install -m644 hardware/sx1262-mode/*.service /usr/local/lib/systemd/system/
sudo install -m644 hardware/sx1262-mode/opi-sx1262-test.conf /usr/local/lib/tmpfiles.d/
sudo systemd-tmpfiles --create /usr/local/lib/tmpfiles.d/opi-sx1262-test.conf
sudo systemctl daemon-reload
sudo systemctl enable --now opi-sx1262-restore.service
```

The restore unit uses the packaged helper under `/usr/share/armbian-config`. On the Zero 2W checkout installation its `ExecStart` points to `/opt/armbian-config-zero2w/share/armbian-config/sx1262_mode.py apply` through a systemd drop-in. The restore unit owns boot activation. Independent boot enablement of protocol services can conflict with that selection.

## Handoff and failure recovery

1. Serialize selectors with `transition.lock`. Check the current systemd states and the actual exclusive flock on the device-owner inode. An external owner, ambiguous service state or missing target prevents the handoff.
2. Atomically record the old and requested modes under `/var/lib/opi-sx1262-mode/`. Stop the old worker and verify that the lock is free. Start the new worker and require two consecutive observations of a single running worker with its MainPID holding the lock.
3. Commit the selection after verification. If startup, ownership verification or saving fails, stop any surviving candidate and restore the previous owner. The UI reports the activation error and rollback outcome. If restoring also fails, retain the pending record for inspection and recovery.
4. `apply` recovers an interrupted handoff and reconciles the live services with the saved choice. Selecting **Off** during recovery stops the transaction's participants without starting a transmitter. This ownership check covers the worker and lock; radio link establishment, OTAA join and packet delivery have separate acceptance tests.

## Zero 2W acceptance, 2026-11-20

| Test | Observation |
|---|---|
| Installed terminal menu | Off → Meshtastic → Reticulum → LoRaWAN. Each successful selection matched the saved state and the kernel's flock owner. |
| Start failure | An instance-specific runtime drop-in made test Reticulum's `ExecStartPre` exit with failure. The menu reported rollback; LoRaWAN regained the lock and remained the saved mode. |
| Health failure | A second drop-in ran a test process that never acquired the lock. The selector detected the mismatch, stopped that live process and restored LoRaWAN. |
| Concurrent changes and foreign lock | A second selector and an independent flock holder were rejected. The saved state remained byte-identical. |
| Interrupted handoff | The selector process was killed while test Reticulum was activating. The journal retained Meshtastic as the committed selection. `apply` restored Meshtastic and cleared the pending transition. |
| Saved-mode restore | After stopping the selected worker, starting the boot restore unit reapplied the saved LoRaWAN selection. This check ran within one boot. |
| End state | The menu reported saved and current **Off**, the test lock was free and all three test worker PIDs were gone. Meshtastic simulation, Reticulum TCP, the two messaging services, gpsd and opi-gnss kept their original service invocation IDs. |

Run the transaction and TUI regressions with `python3 tests/hardware/test_sx1262_mode.py` and `bats tests/bats/sx1262_mode.bats`. The tests also cover an unsuccessful rollback, later recovery, an interrupted transition followed by Off and a failed commit.
