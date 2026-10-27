# Zero 2W controls: WiringPi API and armbian-config

This resumes backlog **6 and 7**, after preserving the experimental browser
results in `9d0a7ede`. Board/image/kernel are unchanged from the
[baseline](zero2w-validation-2026-10-26.md): Orange Pi Zero 2W / H618, Armbian
26.11.0-trunk.108, Ubuntu 26.04, Linux 6.18.57-current-sunxi64. This is evidence
from one board/image, not general Armbian or Raspberry Pi compatibility.

## WiringPi hardware PWM1

The existing library API now reaches a separate H618 kernel-PWM backend, without
MMIO. `pinMode(PWM_OUTPUT/PM_OFF)`, `pwmWrite`, mark-space mode, global/pin/channel
range and logical clock divisor work for **PWM1 / PI11 / physical 32**. The backend
checks the exact verified DT route, controller and driver. It refuses foreign
exports; normal close/exit disables and unexports owned PWM1. PWM5 is reserved by
`ac300-clk` and unchanged.

The logical tick is 24 MHz; the kernel chooses actual hardware clocks. Frequency
is `24000000 / (divisor * range)`. Updates introduce a disabled gap and are not
atomic waveform changes. Balanced PWM, hardware tone, other channels and unknown
DT layouts remain unsupported. See the [WiringPi H618 support contract](https://github.com/shipmarty43/WiringPi/blob/f627770e5a0ae10331e39ef5694ee3928b136897/documentation/english/h618-support.md)
and its public API test for complete behavior and the manual test.

| Requested frequency | Measured frequency | Duty checks |
|---:|---:|---|
| 10 Hz | 9–10 Hz (integer estimate) | 25/50/75% widths passed |
| 100 Hz | 99–100 Hz | 25/50/75% widths passed |
| 1000 Hz | 999–1000 Hz | 25/50/75% widths passed |

Stable 0/100% levels and physical/native/wPi numbering changes also passed on
32 → 1 kOhm → 29. Same tolerance as the previous kernel-only test: frequency
max(2%, 1 Hz), widths max(5%, 50 us). **1 kHz is the highest measured rate, not a
hardware limit.** No FT232H or oscilloscope capture was performed.

The first public API trial failed: the 75 ms HIGH pulse appeared as 48.8 ms.
GPIO IRQ activation can supply an initial event partway through the signal.
Discarding the first event before calculating pulse/frequency fixes the partial
initial pulse. The successful run used unchanged tolerances; a fake-event
regression reproduces the distinction between partial and full pulse widths.

## SPI ownership

Repeated setup and failed mode/BPW/speed ioctls leaked descriptors in the prior
SPI code. The fix closes retired and failed descriptors and opens with CLOEXEC.
A failed open retains the old handle. Once configuration starts, failure leaves
an empty library slot: the kernel may already be partly configured, so the caller
must set up again. NULL buffers, invalid lengths and nonpositive speed are rejected.
All ten public SPI entrypoints and 35 bus/CS slots have fake-I/O regression tests;
**no new physical SPI exchange was performed**.

Host and AArch64 ASan/UBSan tests cover GPIO, SPI, serial PTYs, event/worker lifecycle and the
new fake-sysfs PWM tests. PWM tests include routing rejection, foreign export,
invalid/overflowing period, I/O failure, fork ownership and cleanup.

## Serial API

All eight serial entrypoints are exercised through a real Linux PTY, with injected
partial writes/EINTR and terminal/modem failures. Fixed ignored terminal setup
errors, an uninitialized modem status after failed TIOCMGET, FD leaks, inherited
hardware flow control and incomplete writes. CLOEXEC prevents inherited handles.
Tests cover binary bytes, flush, timeout and descriptor release. PTY tests do not
verify board UART pinmux or physical exchange with GPS/other devices.

## Native Armbian CPU boot defaults

`module_cpu_power` now has these commands, in addition to runtime governor/max:

```sh
armbian-config --api module_cpu_power boot-status
armbian-config --api module_cpu_power persist schedutil 1008000
armbian-config --api module_cpu_power restore-boot
```

The same controls are available from the CPU power menu under boot defaults.
They use `/etc/default/cpufrequtils`, consumed by the enabled
`armbian-hardware-optimize` boot service. **The file applies to all CPU policies.**
Every current policy must support the selected governor/max. No second CPU daemon
is installed and no voltage/thermal protections are changed.

Saving boot defaults does not change the live CPU state. Existing minimum,
boost=false and other static assignments are preserved. Userspace governor and
boost-enabled configurations are rejected by this limited control; so are active
competing managers, symlinks and non-literal shell configuration. The file is read
as data, never sourced. Unsupported syntax requires manual configuration.

Before/after copies live in `/etc/default/cpufrequtils.armbian-config-backup/`.
A lock serializes writers; replacement is atomic, preserves mode/owner and syncs
prepared data to disk. Restore refuses to overwrite intervening manual edits.
One pending saved profile is supported: restore it before saving another. An
interrupted preparation can leave a backup needing manual inspection; no claim of
a transactional filesystem across hardware power loss is made.

Hardware acceptance through the assembled main `armbian-config` command:

1. Saved `schedutil` / 1008000 kHz; live state remained unchanged.
2. Rebooted, verified a changed boot ID and read back `schedutil` / 1008000.
3. Restored the exact original file, verified with `cmp`.
4. Rebooted again, verified another boot ID and `ondemand` / 1416000 kHz.
5. Final source adds disk synchronization/backend checks; its save/restore path
   is exercised again without another reboot. Original file remains restored.

The stock file contains MAX_SPEED=1512000; this kernel's table stops at 1416000,
so the original boot configuration is clamped to 1416000. The new control validates
against the actual kernel table instead of assuming the stock number is supported.

## Display acceptance

XFCE package: `4.20.1-1ubuntu2`. A temporary named 800×450 profile is prepared using
XFCE's own typed properties, matching the first 128 EDID bytes as upstream does.
Only the exact single-HDMI fixture is accepted; this is a test harness, not a new
generic backend. Original settings are backed up before modification. A timed
rollback restores the original mode; final cleanup removes the temporary profile.
See [the test fixture](zero2w-xfce-profile.sh).

- Native profile application selected 800×450 at 60.05 Hz.
- The operator confirmed two unplug/replug cycles with automatic picture return.
  Post-test read-back still showed the named profile and 800×450. The bounded
  status recorder captured only `connected`, with a gap between its two runs;
  it does **not** supply timestamped evidence of the physical disconnects.
- A new LightDM/XFCE session (84, replacing original session 8) automatically
  applied the named profile at 800×450. An earlier read attempt ran after a short
  session had already ended and failed X authorization; it was not counted as a
  successful persistence test.
- Cleanup removed the test profile and restored `ActiveProfile=Default`,
  `AutoEnableProfiles=3`, `Notify=1`, 1024×600 at 59.85 Hz and no primary-output
  designation, matching the initial state. The rollback timer was stopped.
- The assembled configurator correctly found the active graphical session and
  reported HDMI plus LightDM. No distinct-DM switch was attempted.

This qualifies one profile across logout/login and operator-observed hotplug.
A reboot **with the saved non-default profile** remains untested.

Upstream format reference: [XFCE 4.20.1 profile writer](https://github.com/xfce-mirror/xfce4-settings/blob/xfce4-settings-4.20.1/common/xfce-randr.c)
and [profile matching](https://github.com/xfce-mirror/xfce4-settings/blob/xfce4-settings-4.20.1/common/display-profiles.c).

## Remaining acceptance

- Real I2C/SPI/UART devices and other physical GPIOs/channels; FT232H acquisition.
- PWM signal qualification above 1 kHz, other channels and suspend/resume.
- Display profile across reboot; hotplug with continuous event capture and longer cycles.
- Switching **distinct** display managers; tests with LightDM do not establish this.
- CPU consumption/thermal behavior and MAX17043/DFR0528 integration.

No full API, all-board compatibility or production-readiness claim is implied.


## Retained evidence and final state

Selected sanitized [logs and tested-source hashes](evidence/2026-10-27/controls/)
are covered by the parent SHA256SUMS manifest. The final source hashes from the
board match the local sources. The 41 relevant Bats tests passed. Full raw
selected logs are additionally kept off the SD card in the private workspace
backup directory; browser profiles, credentials and SD contents are not published.

Final state: ordinary XFCE, 1024×600 HDMI, LightDM, CPU governor `ondemand` with
maximum 1416000 kHz, original CPU boot file restored, PWM1 disabled/unexported,
and test timers stopped. The pre-existing `pwm1-pi11` overlay remains enabled;
the physical resistor wiring remains 32 ↔ 29. Browser experiment unchanged.
