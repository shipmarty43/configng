# Chromium retry on Zero 2W, 2026-10-26

Follow-up to the [initial failed browser trial](zero2w-validation-2026-10-26.md).
Same board/image, Chromium `156.0.8078.47-1xtradeb1.2604.1`, Mesa
`26.0.8-1ubuntu0.3`, and pinned external VA-API bridge. No package changes,
system-wide flags or browser sandbox-disabling flags were applied in this retry.

## Results

All eight fresh-profile trials responded to DevTools. All selected
`FFmpegVideoDecoder`, with `kIsPlatformVideoDecoder=false` and an empty
`SystemInfo.getInfo.gpu.videoDecoding` array. **Browser hardware decoding is
still not working in these tested configurations.**

| Case | Graphical backend / additional settings | Clip result |
|---|---|---|
| Direct binary, defaults | ANGLE automatically fell back from desktop GL to GLES on Mali | Repeated play/end events; initial frame-counter collection was incomplete |
| Distribution wrapper, defaults | Same Mali GLES renderer | Same initial counter limitation |
| Direct, forced ANGLE GL | EGL initialization failed; GPU process exited, hardware renderer absent | 60 frames, 5 dropped |
| Direct, VA-API + ANGLE GLES | Mali-G31/Panfrost | 60 frames, 0 dropped |
| Direct, VA-API + GLES + explicit render node | Mali; bridge loaded and detected one Request API decoder | 60 frames, 0 dropped; still software decode |
| Wrapper, VA-API + ANGLE GLES | Mali-G31/Panfrost | 60 frames, 1 dropped |
| Wrapper, original VA-API + ANGLE GL flags | EGL initialization failed, hardware renderer absent | 60 frames, 8 dropped |
| Direct, explicit render node + VaapiIgnoreDriverChecks | Mali; bridge loaded | 60 frames, 0 dropped; still software decode |

Clip: synthetic 320×240 H.264, 30 fps, 2 seconds. These single short runs are
functional checks, not representative performance measurements. The last six
trials disabled looping and checked explicit `totalVideoFrames`,
`droppedVideoFrames`, `ended`, `readyState` and media errors. In the first two,
the initial probe serialized `VideoPlaybackQuality` as `{}` and sampled during
a loop boundary; their zero final timestamp is not evidence of frozen playback.
Retained Media events show repeated end/seek cycles, but no frame-count pass is
claimed for those two trials.

## What this narrows down

1. The earlier startup hang was **not reproduced**. Each retry used a new
   profile, opened `about:blank`, enabled Media diagnostics, then navigated to
   the same local clip. The original attempt opened the clip directly. This is
   not a controlled proof that the profile, startup URL, or a particular flag
   caused the previous hang.
2. Forcing `--use-angle=gl` reproducibly failed GPU initialization on this image.
   `--use-gl=angle --use-angle=gles` used Mali-G31/Panfrost successfully. This
   explains a graphics failure, not necessarily the old whole-browser hang.
3. Without a device override, Chromium logged that VA-API pre-initialization had
   not run or had failed to select a suitable render node. Adding
   `--hardware-video-device-path=/dev/dri/renderD128` changed the log to the
   external bridge detecting one Request API decoder. Hardware profile
   enumeration remained empty. The precise reason profiles are rejected or
   filtered remains unresolved; do not label this a proven decoder-kernel bug.
4. GPU rendering and VPU decoding are separate: Mali rendering worked while
   H.264 still used the CPU. The process-scoped `VaapiIgnoreDriverChecks` probe
   did not change that outcome and was not made a persistent workaround.

The primary Chromium [VA-API implementation](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/media/gpu/vaapi/vaapi_wrapper.cc)
documents explicit render-node selection; its
[verification guide](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/gpu/vaapi.md)
describes checking advertised codecs and actual decoder selection. These sources
guided the probes; live installed-binary results above are the evidence.

## Reproduction and next step

Run from the ordinary user's XFCE terminal, using a fresh disposable profile
and the local synthetic `test.html`/`test.mp4` pair. The driver directory is the
uninstalled build from the earlier report, made readable to that user:

```sh
trial_profile=$(mktemp -d)
env LIBVA_DRIVERS_PATH=/absolute/path/to/driver \
  LIBVA_DRIVER_NAME=v4l2_request \
  LIBVA_V4L2_REQUEST_MEDIA_PATH=/dev/media0 \
  /usr/lib/chromium/chromium --user-data-dir="$trial_profile" \
  --no-first-run --no-default-browser-check \
  --use-gl=angle --use-angle=gles \
  --enable-features=AcceleratedVideoDecodeLinuxGL \
  --hardware-video-device-path=/dev/dri/renderD128 \
  --enable-logging=stderr '--vmodule=*vaapi*=3,*video_decoder*=3' \
  file:///absolute/path/to/test.html
```

This is a diagnostic reproduction, **not an accelerated-YouTube launcher**.
The automated runs used a user systemd service, a 110-second runtime limit,
five-second stop timeout and DevTools bound to loopback port 9223. The harness
captured `Media.playerPropertiesChanged`, media events/messages,
`Runtime.evaluate` playback counters and `SystemInfo.getInfo` before stopping
the test service. It did not visit YouTube or use a personal browser profile.

Next inspect the installed Chromium build's VA-API capability filtering and
the bridge's profile/config/surface queries, with libva tracing if needed.
Only after a hardware decoder is actually selected should display import,
longer/high-resolution playback and real YouTube streams be qualified.

No `--no-sandbox` or `--disable-gpu-sandbox` flags were used. Nevertheless CDP
reported `gpu.auxAttributes.sandboxed=false` in the Mali GLES trials (and true
in the failed GL trials). This is a separate observation requiring investigation,
not a claim that the complete browser sandbox was verified or disabled by us.

## Saved evidence

The [summary JSON](evidence/2026-10-26/browser-retry/summary.json) retains command
flags, actual decoder, renderer, playback counters and reported sandbox state.
Adjacent logs are normalized only for private paths, ephemeral debugger IDs
and trailing whitespace. Full CDP events, commands, results and the lab harness
are archived privately off the SD card at
`backups/zero2w-browser-retry-20261026/evidence.tar.gz` in the enclosing workspace.
The test service was confirmed inactive/dead after the last trial. Isolated
profiles remain on the board for inspection; normal profiles are untouched.
