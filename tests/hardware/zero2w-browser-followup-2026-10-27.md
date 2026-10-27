# Browser video follow-up — 2026-10-27

Checkpoint recorded when the user reported another power outage. Work later
resumed: see the [direct-output report](zero2w-browser-direct-2026-10-27.md) for
recovered logs, final EGL rerun and additional playback tests. This supplements the
[previous report](zero2w-browser-wayland-2026-10-26.md).

## Playback and frame pacing

Same Orange Pi Zero 2W, kernel 6.18.57-current-sunxi64, Mesa 26.0.8,
Chromium 156.0.8078.47 and isolated pre-export VA driver as the previous report.
The driver SHA-256 is
`f47e3158998749faaf08005a9fcd006ed0b32a2ada68daa87da9cdd43bc165f4`.
XFCE/X11 ran nested Weston with its GL renderer at 960×540; Chromium used
Wayland, ANGLE/GLES and a disposable profile. XFWM compositing was enabled.
The synthetic fixture was 60 seconds of 1920×1080 H.264 High, limited-range
BT.709, 30 fps, no audio, made by looping the existing ten-second fixture six
times with stream copy. This is not an audio-sync or YouTube acceptance test.

The updated [harness](zero2w-browser-pixels.py) samples playback every 0.5 seconds
and reports counter differences after the first sample at or beyond five media
seconds. Runs used `--preexport --seeks ''` and the isolated driver directory.

| CPU governor | Full clip dropped / total | After warm-up dropped / total | After warm-up loss |
|---|---:|---:|---:|
| ondemand | 100 / 1800 | 93 / 1642 | 5.66% |
| performance | 104 / 1800 | 102 / 1635 | 6.24% |

Both runs selected `VaapiVideoDecoder`, reported the platform decoder, reached
60 seconds and ended without a media error. One run per setting does not establish
a general performance comparison. It does show that this performance-governor
trial did not remove the sustained drops. It is not a recommended workaround.

The ondemand JSON was copied off the board before the outage; the
[public extract](evidence/2026-10-27/ondemand-summary.json) retains all samples.
Performance numbers above were observed in completed command output before the
outage. Its full JSON, temperatures and restoration log were still on the board
and had **not yet been copied off the SD card** at this checkpoint. They have
since been recovered; the source locations were
`/root/opi-validation-20261027/` and the isolated user directory
`20261027-1080-hardware-performance-60s/`.

## Color conversion experiment

The [standalone EGL test](zero2w-egl-yuv-color.c) allocates one NV12 DMA-BUF
through the isolated VA driver, fills six constant YUV colors, imports each with
BT.601 and BT.709 EGL hints, and compares GPU pixels against CPU matrix formulas.
It does not decode a video or execute Chromium.

The [retained log](evidence/2026-10-27/egl-yuv-color.log) reports Mali-G31 MC1
(Panfrost), maximum formula error of one RGB code value, and a maximum error of
21 values when the BT.601 hint is used for the BT.709 reference colors. This
isolates and supports the suspected matrix-selection problem; it does not prove
that a modified Chromium renders correct pixels end to end.

The tested version compiled with `-Wall -Wextra -Werror` and passed on the board.
Four descriptor bounds/alignment assertions were subsequently added to the
published source. The original log predates those assertions; the final source
was rebuilt and passed after power returned, with its SHA-256 recorded in the
resumed report.

An opt-in [Chromium patch draft](patches/chromium-wayland-bt709-egl-import-draft.patch)
selects BT.709 for BT.709 imports only on explicit Wayland without overlay
delegation. It targets Chromium revision
`1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775` and remains **unbuilt and uninstalled**.
The pinned source currently defaults this matrix to BT.601 to match overlay
assumptions. Preserve those defaults outside the experiment.

A full browser build was not started: the host had about 48 GiB free disk,
whereas the pinned [Chromium build instructions](https://chromium.googlesource.com/chromium/src/+/1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775/docs/linux/build_instructions.md)
require at least 100 GB. Compilation and pixel comparisons are still required.

## State and next restart

- CPU governor was restored to `ondemand` and read back before the outage.
- XFWM compositing was still enabled; the proposed no-compositing trial had not
  started. Do not attribute a result to that experiment.
- No browser qualification run was active at the last observation. Nested Weston
  was a transient user service with a 30-minute limit; no post-outage stop is claimed.
- No global VA driver installation, boot change or GPIO manipulation was performed
  during these follow-up tests. Existing physical 32↔29 resistor wiring is unchanged.

After power returns: inspect boot/filesystem/GPU logs, recover remaining raw
results, verify governor and desktop session, rebuild and rerun the final EGL
test, then compare the same minute clip with XFWM compositing temporarily off
and restore its original setting. A Chromium build with the draft must separately
pass software-versus-hardware pixel comparisons, seeks and sustained playback.
