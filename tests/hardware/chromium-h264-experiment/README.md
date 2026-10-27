# Opt-in Cedrus browser experiment

This directory supplies a small YouTube H.264 codec-negotiation extension and
launchers for the exact Zero 2W image described in the board reports. It does not
make the VA bridge production-ready, fix BT.709 colors, or enable hardware VP9,
AV1 or encoding. The source and GPL license of the external driver remain separate.

The extension runs at document start in the page's MAIN world, only on the listed
YouTube hosts. It reports unsupported video codecs as unavailable through
MediaSource, canPlayType and MediaCapabilities; H.264 and audio capability results
are forwarded unchanged. It does not send data, read cookies or block ad requests.
See the [Chrome content-script specification](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts)
for the manifest execution-world and timing fields. `node test.cjs` checks codec
rejection, preserved H.264/audio behavior, receiver binding and native errors.

`opi-cedrus-browser` requires an ordinary user and an existing Wayland session.
It uses a separate profile and process-local VA variables, with no remote-debugging
port or sandbox-disabling flags. Its default data directory is
`~/.local/share/opi-cedrus-browser`, containing `driver/v4l2_request_drv_video.so`
and `extension/{manifest.json,h264.js}`. `OPI_CEDRUS_DATA_DIR` can select another
experiment directory. A URL or local video path may be supplied as an argument.

`opi-cedrus-session` is for a display-manager login, not an active X11 terminal.
It runs Weston directly on DRM with the existing HDMI mode, uses the observed
`WESTON_DISABLE_ATOMIC=1` workaround only for this process, and closes the session
when Chromium exits. Install the two scripts to `/usr/local/bin` and the desktop
entry to `/usr/share/wayland-sessions` only after validating on the target board.
It does not replace the default XFCE session or change boot parameters.

## Acceptance limits

- Nested Weston on X11 had sustained frame drops; directly displayed legacy KMS
  significantly reduced them. Atomic KMS failed on this image: advancing browser
  counters without a visible image was rejected as an acceptance result.
- The board currently has 64 MiB CMA. Concurrent graphical sessions plus 1080p
  decode exhausted it during a trial. Closing surplus test compositors freed
  memory; a larger CMA reservation and longer stress tests remain separate work.
- YouTube trials must include a separate warm-up and a continuous measurement
  window. A reset, advertisement, seek or page failure invalidates the window.
  A short successful hardware decode does not prove uninterrupted YouTube playback.
- Colors remain experimental; audible output and A/V synchronization are not yet
  qualified. See the [resumed report](../zero2w-browser-direct-2026-10-27.md).

## Repeat the warmed streaming measurement

From a terminal inside a working direct legacy-KMS Weston session, as its normal
user (replace the three absolute paths):

```sh
python3 /path/to/zero2w-youtube-smoke.py \
  --driver /path/to/driver-preexport \
  --extension /path/to/chromium-h264-experiment \
  --output /path/to/new-private-run --warmup 15 --seconds 90
```

Add `--software` for the H.264 CPU control; add both `--software --native-codecs`
for the no-extension control. `--audio` explicitly unmutes the player, but is not
an A/V-sync or audibility test. Keep the video playing during the measurement;
backward seeks and source resets invalidate the counter baseline. Forward seeks
and other user interactions must also be excluded when reviewing a run. Partial samples survive
normal interruption. The harness deadline and its browser process-group cleanup
are separate from any systemd timeout used to bound a board session.

For a manual check choose **Chromium H.264 (experimental)** at the login screen.
Wait for the page to load, start a video and let it play beyond a minute. Compare
that observation separately from instrumented/CDP tests; their outcomes differed
on this board. To return to XFCE, close Chromium and select XFCE at the next login.
