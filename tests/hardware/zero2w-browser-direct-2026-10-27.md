# Direct HDMI browser playback — 2026-10-27

Follow-up to the [power-outage checkpoint](zero2w-browser-followup-2026-10-27.md).
The board booted, `admin1` logged into XFCE, and the remaining performance logs
were recovered off the SD card. No failed system units or matching EXT4/I/O,
Panfrost fault/timeout or Cedrus fault/timeout messages were found in the initial
post-boot checks. HDMI audio did report a simultaneous-stream error; audible
output was not qualified because the user has no audio output connected.

The kernel, Chromium, Mesa and isolated VA bridge match the previous report.
CPU governor remained `ondemand`; XFWM compositing was restored to its original
`true` value after its test. No boot, GPIO or CPU-persistence changes were made.

## What improved, and what did not

The synthetic fixture is the same 60-second, 30 fps, BT.709 H.264 1080p clip.
Counter differences exclude the first sample at or after five media seconds.
These are single diagnostic runs, not repeated statistical benchmarks.

| Path | Decoder | Whole clip dropped / total | After warm-up dropped / total | Result |
|---|---|---:|---:|---|
| Nested Weston, XFWM compositing off | VA-API | 92 / 1800 | 86 / 1642 (5.24%) | Drops persisted; original XFWM setting restored |
| Nested Weston, overlay delegation opt-in | VA-API | 84 / 1800 | 80 / 1633 (4.90%) | Did not solve drops; no proof that overlays were actually promoted |
| Nested Weston, CPU control | FFmpeg | 42 / 1800 | 11 / 1637 (0.67%) | Higher process CPU time: 136.5 s versus about 41 s for nested hardware runs |
| Direct DRM, atomic KMS | VA-API | 0 / 1800 | 0 / 1639 | **Rejected**: HDMI atomic commits failed; counters did not prove visible playback |
| Direct DRM, legacy KMS | VA-API | 7 / 1800 | 4 / 1643 (0.24%) | User confirmed visible video; Cedrus selected, no software fallback observed |

The atomic result was initially promising from counters alone, then rejected
when Weston reported `atomic: couldn't commit new state: Invalid argument`
and the user reported no visible browser/video. Do not cite it as a smooth
hardware-display pass. This is why physical output checks accompany counters.

`WESTON_DISABLE_ATOMIC=1` in **only the test compositor's environment** made the
image visible. Weston used DRM directly, the existing HDMI mode and Panfrost GL
rendering. XFCE remained on VT7; each bounded test used VT8 and returned to VT7.
The [official Weston backend documentation](https://wayland.pages.freedesktop.org/weston/toc/running-weston.html)
describes direct DRM/KMS versus nested X11 operation. The workaround was verified
against the installed Weston 14 DRM backend and actual output; its underlying
atomic-KMS failure still needs investigation.

A ten-second driver trace measured 300 decode-completion waits: median 10.34 ms,
p95 13.11 ms, maximum 16.24 ms. Reader waits were at most 0.54 ms. Trace logging
can affect timing. These data do not establish sustained decode throughput, but
do not show a long reader-buffer stall in this run.

## Memory and color limits

CMA was only 64 MiB. While multiple graphics contexts and 1080p decode coexisted,
the kernel reported failed contiguous allocations of 765 pages and as little as
648 KiB free CMA. The visible legacy test still completed with VA-API. Stopping
the unused nested compositor and completing the test freed memory: a subsequent
read showed 35,004 KiB free CMA. Long/parallel workloads need additional memory
validation; no larger CMA reservation has been applied or tested.

The final EGL color-test source was rebuilt with `-Wall -Wextra -Werror` and
passed on the board. SHA-256:
`a9277802fa5172f8eaeeca4ec0f5080fe680e1f5ecc8715015ab38cd47e929d7`.
The matrix-formula error remained at most one RGB code value, and the wrong
BT.601 hint produced up to 21 values of error against BT.709. This is a GPU
conversion test, not a Chromium color fix. At the user's request the Chromium
color patch/build is deferred; its draft is still unbuilt and uninstalled.

## YouTube and separate warm-up

The [new bounded harness](zero2w-youtube-smoke.py) uses an isolated profile and
an [opt-in H.264 extension](chromium-h264-experiment/). The extension's behavior
was checked on the live page: H.264 available, VP9/AV1 unavailable. A manual
launcher is separate from the instrumented harness and opens no debugging port.

The first live legacy-KMS run selected Cedrus H.264 Main at 854×480. It later
showed YouTube's “Something went wrong” message and reset the video's counters.
It is **not** a successful 90-second run, even though the early harness returned
`capture_complete`. That flag only meant a screenshot was captured; the whole
run is rejected for uninterrupted-playback acceptance.

At the user's request the harness now waits for at least 15 seconds of playback,
three stable samples of video dimensions, visible/unpaused ready-state ≥3, and
at least two seconds of buffered video. It saves warm-up samples separately,
then takes a fresh counter baseline for the requested measurement interval.
Counter/time resets, advertisements, backward seeks and disappearance of the main video
invalidate the interval instead of producing a misleading zero-drop result.

The new warm-up trials also reset at about 41–44 media seconds:

- Hardware H.264 with the extension.
- CPU H.264 with the same extension; decoder `FFmpegVideoDecoder`.
- CPU with native codec selection and **no extension**.

Thus the failure reproduced independently of the Cedrus path and extension.
The H.264 CPU trial still had about 19 seconds buffered immediately before the
reset. The inspected hardware network log showed 18 HTTP 200 video responses,
one 204 response, and no media-decoder error; canceled requests were logged as
`net::ERR_ABORTED`. A 401 response from an account sign-in endpoint is not proof
of the playback failure's cause. The user reported possible Internet instability.
Network/site/session or instrumentation issues remain possible; do not label this
a proven driver fault, a proven network outage, or a passed streaming test.

## Manual playback result

The user subsequently used the installed session command with ordinary Chromium
controls and confirmed: **the video continued for more than one minute**. During
that run the experimental VA driver was mapped into Chromium's GPU process and
it held `/dev/media0` and `/dev/video0` open. This provides an encouraging manual
hardware-playback observation beyond the automated failure point, not a measured
90-second or drop-free pass. Its exact resolution and frame-loss count were not
collected. The launcher opens no debugging port and does not run the automation
harness. We have not established which difference caused the automated failures.

## Reproducibility and installed experiment

Public selected results are under [resumed evidence](evidence/2026-10-27/resumed/).
Full logs, synthetic frame captures and test scripts were archived privately off
SD under `backups/zero2w-browser-followup-20261027/`; browser profiles and temporary
web directories are excluded. YouTube screenshots, full events and signed network
URLs are not published. Keep only sanitized counters and error classifications.

Two launchers and a separate `Chromium H.264 (experimental)` Wayland session entry
were installed on the board, together with a private driver/extension directory:

- `/usr/local/bin/opi-cedrus-browser`
- `/usr/local/bin/opi-cedrus-session`
- `/usr/share/wayland-sessions/opi-cedrus.desktop`
- `/home/admin1/.local/share/opi-cedrus-browser/`

The browser uses its own profile, process-local VA settings and H.264 negotiation;
the session scopes the legacy-KMS workaround to Weston. XFCE remains the configured
default. Closing Chromium ends this experimental session. Source and usage are
in the [launcher directory](chromium-h264-experiment/). Display-manager login itself
still requires a separate user-selected login check; the same session command is
validated through a bounded PAM/logind session on VT8, with the user confirming
manual playback beyond one minute.

Removal is limited to the three installed files and the dedicated per-user data
directory above; preserve that profile first if the user has added anything useful.
Do not remove normal Chromium profiles, Weston packages or XFCE configuration.

The five-minute manual test session ended at its configured deadline and returned
to XFCE on VT7. Final readback confirmed `ondemand`, XFWM compositing enabled,
and no remaining active `opi*` test units. The installed experiment remains
available for a user-selected login; it is not an autostart service.

Remaining acceptance: uninterrupted instrumented warmed YouTube playback, audible output/A/V
sync, higher-resolution adaptive streams, CMA sizing, long playback, corrected
BT.709 colors, and an upstreamable solution for the atomic-KMS failure.
