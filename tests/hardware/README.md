# Orange Pi Zero 2W development handoff

This directory preserves board evidence and reproducible experiments for future
Armbian work. Start with the [2026-10-26 validation report](zero2w-validation-2026-10-26.md).
Results describe one H618 board and image, not universal Armbian support.

## Baseline and source provenance

- Board: Orange Pi Zero 2W, Allwinner H618, Mali-G31 MC1, 4 GB RAM.
- Image: Armbian community 26.11.0-trunk.108, Ubuntu 26.04, AArch64.
- Kernel: `6.18.57-current-sunxi64`; Mesa: `26.0.8-1ubuntu0.3`.
- Configuration implementation tested before these follow-up experiments:
  [configng 8ee0fc3c](https://github.com/shipmarty43/configng/commit/8ee0fc3cef28752b6db88fbc3252579c9fcb30d5),
  branch `codex/display-controls`. New compute/VA-API test sources are in this directory.
- GPIO/PWM library and probes:
  [WiringPi f774244](https://github.com/shipmarty43/WiringPi/commit/f774244d908a3c3e7e335205f7a9e308cf203434),
  branch `codex/h618-support`; see its
  [H618 support contract](https://github.com/shipmarty43/WiringPi/blob/f774244d908a3c3e7e335205f7a9e308cf203434/documentation/english/h618-support.md).
- Application/older hardware bring-up:
  [armbian-gui caa06d8](https://github.com/shipmarty43/armbian-gui/commit/caa06d88313cddedd15ace4aa8c67c7b06c8a37b),
  branch `codex/opi-hardware-bringup`. Old-image overlays require revalidation
  against the new kernel; they are not substitutes for its stock overlays.
- VA-API bridge: Ondrej Jirman's
  [libva-v4l2_request](https://xff.cz/git/libva-v4l2_request/), exact commit
  `cac6ece0e23ac1f944dd3af266680aff0c3184df`, reported project version 1.2,
  GPL-3.0-or-later. Tested unmodified as an external driver, not vendored or
  installed system-wide. The similarly named Apple AVD fork was inspected but
  was not the driver used for these results.

The [2026-10-27 follow-up](zero2w-browser-followup-2026-10-27.md) records minute-long
frame-drop measurements, isolated EGL color tests and the power-outage checkpoint.
The [resumed direct-HDMI report](zero2w-browser-direct-2026-10-27.md) records the
legacy-KMS workaround, reduced synthetic frame drops, warmed streaming failures
and the separately confirmed manual YouTube playback.

The [controls follow-up](zero2w-controls-2026-10-27.md) tracks work on backlog
**6 (WiringPi API)** and **7 (armbian-config)**. These stable numbers refer to the
[last numbered backlog](zero2w-backlog.md), not row numbers in the table below.

## Integration boundaries and remaining acceptance

| Area | Evidence obtained | Next development/acceptance step |
|---|---|---|
| GPIO, IRQ, software PWM/tone | Real loopback, edges, timing and ownership tests in WiringPi | Protocol/device-specific tests; do not substitute software timing for hardware peripherals |
| Hardware PWM1 | Stock overlay, physical 32 → 29, 10/100/1000 Hz and 0–100% duty tests | [Public PWM1 API tested](zero2w-controls-2026-10-27.md); qualify other channels and higher rates with suitable equipment |
| CPU power controls | Runtime governor and frequency readback, invalid-value rejection, reboot reset | [Native Armbian boot defaults and exact rollback tested](zero2w-controls-2026-10-27.md); thermal/power measurements and MAX17043 integration |
| Display / DM | XFCE panel, resolution switch/revert, LightDM boot with HDMI attached | [Named profile across login and operator-observed hotplug tested](zero2w-controls-2026-10-27.md); non-default profile across reboot, continuous hotplug capture and distinct-DM switch |
| OpenGL ES | Panfrost pixel readback and accelerated XFCE | Sustained workloads, games, frame pacing and thermal behavior |
| Vulkan graphics / compute | PanVK cube on HDMI; 524,288 integer compute results checked | Experimental opt-in only; floating-point/workload qualification and driver stability |
| Video decoder | Cedrus GStreamer: H.264, HEVC, VP8, MPEG-2; VA-API H.264 byte-exact readback | Realistic resolution/bitrate, audio sync, display import, long playback |
| Browser / YouTube | [Experimental DMA-BUF patch + nested Wayland](zero2w-browser-wayland-2026-10-26.md): visible hardware H.264 at 720p/1080p and a short YouTube 480p stream | Direct legacy-KMS reduced drops; manual playback confirmed beyond one minute. Fix BT.709, qualify warmed long/adaptive playback, CMA sizing and desktop integration |
| Hardware encoding | No encoder exposed by tested stack; VA-API reports decode entrypoints | Separate kernel/userspace driver research; do not advertise hardware encoding |
| CVBS | Offline Android/vendor research in [CVBS notes](zero2w-cvbs.md) | Native driver bring-up and capture through expansion board + EasyCAP |
| USB host/device | [Boot-role module and local DT tests](zero2w-usb-role.md); no board trial yet | Qualify USB0 in both roles with UPS power and preserve USB1 modem/hub; add explicit gadget functions |
| FT232H | Not connected, no capture performed | Select/validate acquisition mode and bandwidth, then protocol captures |

The tested kernel decoder advertises H.264/HEVC/VP8/MPEG-2, not VP9 or AV1.
Use an H.264 (`avc1`) browser stream for initial acceptance. Browser rendering
acceleration, `vainfo`, and a VA-API FFmpeg pass each cover only part of that path.
Neither decoder enumeration nor a launch flag proves hardware YouTube playback.

## Reproduce and retain evidence

- [OpenGL ES test](zero2w-gles-smoke.c), [Vulkan compute host](zero2w-compute.c)
  and [shader](zero2w-compute.comp): build/run commands are in the validation report.
- [GStreamer decoder comparison](zero2w-codec-smoke.sh) creates synthetic clips
  and checks every decoded frame against software output.
- [VA-API H.264 comparison](zero2w-vaapi-smoke.sh) uses an explicitly selected
  external driver, verifies Cedrus selection, requires hardware-surface readback
  and compares every byte. See the report for the pinned driver build.
- [Browser pixel harness](zero2w-browser-pixels.py) captures actual frames and seek positions;
  see the [external-driver experiment](zero2w-browser-wayland-2026-10-26.md) before using it.
- [Retained evidence](evidence/2026-10-26/) contains selected logs and SHA-256
  checksums. Paths in public logs are normalized; raw logs are archived privately
  off the SD card. Checksums protect file integrity, not proof of test validity.

For each future run record the board/image/kernel, package and source revisions,
physical wiring, exact command, exit status, observed driver, result, cleanup,
and remaining limitations. Preserve failed trials too. Keep test logs outside
temporary directories before reimaging; never publish SD images or personal
browser profiles as test evidence.

Current wiring is **32 ↔ 29 through 1 kOhm**. Older GPIO/IRQ tests used **37 ↔ 29**;
they must not be rerun with the current connection. `pwm1-pi11` remains enabled
in `/boot/armbianEnv.txt`; PWM1 was disabled/unexported after testing, but PI11 is
still reserved by its kernel pinctrl. PWM5 belongs to the Ethernet clock and must
not be touched. 1 kHz is the highest measured test frequency, not an established
hardware limit. Kernel edge timestamps do not qualify high-frequency signal shape.

## Changes made to the test image

Runtime CPU changes were reset by reboot. LightDM remains the display manager.
The boot environment was backed up before enabling the stock PWM1 overlay.
Development/test packages, native Chromium and nested Weston were installed. The original
Chromium master preferences were retained during package configuration.
The VA-API driver was built in the validation workspace and copied into an
isolated user test directory; no global libva or experimental PanVK setting was
installed. A second, opt-in VA-API driver build with the experimental pre-export
DMA-BUF patch remains in the isolated test directory; nested Weston and test
HTTP/browser services were stopped. Browser tests use a separate profile and a bounded transient user
service, without sandbox-disabling command-line flags. See the report for failure details.

This is a development baseline for the fork. No upstream Armbian acceptance,
packaging, or production-readiness claim is implied by these experiments.
