# Chromium/Cedrus: DMA-BUF fix and remaining qualification, 2026-10-26

**Experimental hardware browser decoding now produces images, including a real
YouTube H.264 stream. It is not ready to enable by default.** Color conversion,
frame drops and integration with the normal desktop remain open.

This continues the [initial retry matrix](zero2w-browser-retry-2026-10-26.md).
Board/kernel/Mesa/Chromium versions are unchanged from the
[baseline](zero2w-validation-2026-10-26.md). Weston `14.0.2-5` was added as a
nested, GL-rendered Wayland compositor inside the existing XFCE/X11 desktop.
The display manager, login session and system VA-API libraries were not replaced.

## What was actually wrong

There were several independent issues, not a single browser startup failure:

1. **The original 320×240 test favors software decoding.** The installed
   Chromium source has a 360-line priority cutoff with resolution-based decoder
   priority enabled by default. That clip is insufficient to test hardware
   decoder selection. At 720p the browser attempted VA-API.
2. **The early empty CDP capability list was not conclusive.** Opening
   `chrome://gpu` caused capabilities to be populated: H.264 baseline/main/high,
   VP8, HEVC main/main-still-picture. Advertised 4096×4096 limits were not tested.
3. **X11 output negotiation failed.** At 720p VA-API opened Cedrus, then the
   pipeline attempted an image processor and fell back to FFmpeg. Native Wayland
   in nested Weston accepted NV12 directly, without an image processor.
4. **Unmodified VA-API bridge produced green frames.** It allocated standalone
   storage when Chromium exported a surface *before decoding*, then discarded
   that backing and decoded into a new CAPTURE buffer. Chromium retained the
   earlier DMA-BUF. The browser reported `VaapiVideoDecoder` and progressing
   frames while the captured image was uniformly RGB `(0,136,0)`.

The last defect explains why counters and `kIsPlatformVideoDecoder=true` alone
are not enough. A software control displayed the synthetic pattern correctly.

## Experimental driver patch

[Patch](patches/libva-v4l2-request-preexport-dmabuf.patch), against unmodified
[libva-v4l2_request](https://xff.cz/git/libva-v4l2_request/) commit
`cac6ece0e23ac1f944dd3af266680aff0c3184df` (GPL-3.0-or-later).
The patch is a separately licensed external-driver experiment, not linked into
configng, not a kernel patch, and not a system-wide driver installation.

With process-local `V4L2R_PREEXPORT_DMABUF=1`, the patch:

- Imports the already exported storage into the decoder's CAPTURE queue, keeping
  the same memory visible to Chromium; no CPU pixel copy is introduced.
- Checks the negotiated layout, keeps independent fd ownership, and waits for
  references/readers before reuse. Rejects unsupported layouts instead of
  replacing the exported storage.
- Waits for decode completion before returning `vaEndPicture`, since this path
  does not supply a producer fence to the browser. This serializes decoding and
  is a correctness prototype, not an optimal asynchronous implementation.
- Is limited to pre-exported H.264, single-planar V4L2 CAPTURE, linear NV12 and
  DMA-BUF-import-capable devices. Other codecs/devices are not qualified. It does
  not solve the existing converter-backed surface lifecycle.

The final patch was built on the board with GCC 15.2.0. The existing FFmpeg
VA-API smoke test, run against that build **without the opt-in variable**, still
passed: 60×320×240 H.264 frames matched software NV12 output byte for byte.
Timeout/error/reallocation paths need dedicated fault-injection coverage before
promoting this experiment into a generally supported driver.

## Observations and limits

| Trial | Actual decoder and result |
|---|---|
| Unmodified bridge, Wayland, 720p | VA-API selected; all pixels in the captured frame were green. Failed image correctness despite advancing counters |
| Patched bridge, 720p baseline | Test pattern visible, `VaapiVideoDecoder`; final-patch repeat: 180 frames, 13 dropped, successful seeks to 1/3/5 seconds |
| Final patch, BT.709 H.264 High 1080p, 10 seconds | `VaapiVideoDecoder`, 300 frames, 18 dropped; ended without media error. Captures after seeking to 1/3/5 seconds reached the requested positions |
| Software control, same 1080p media | `FFmpegVideoDecoder`, 300 frames, 32 dropped; matching seek positions, different RGB colors |
| YouTube, fresh profile, H.264 main 854×480 | `VaapiVideoDecoder`, Cedrus NV12 864×480 backing, visible film image. Sample at 42.67 seconds: 1285 frames, 123 dropped; no media error |

The YouTube experiment used the [official Blender film](https://www.youtube.com/watch?v=aqz-KE-bpKQ),
with a temporary page-initialization override of `MediaSource.isTypeSupported`
and `HTMLMediaElement.canPlayType` rejecting VP9/AV1. No extension, account login
or persistent codec preference was installed. This proves only that short H.264
MSE playback path, not default YouTube behavior or hardware VP9/AV1 support.
Audio was muted during sampling; audio/video synchronization was not qualified.

These are sequential single-run diagnostics under nested Weston, with browser
logging and captures; they are not a controlled performance benchmark. The
software/hardware dropped-frame counts do not establish a general speedup.
Neither 1080p60, long playback, thermal behavior nor adaptive resolution changes
has been accepted. No hardware encoding claim is made.

### Color correctness is still failing

The early untagged clip showed a color difference. Repeating with explicitly
BT.709-tagged H.264 did **not** fix it. In the 1080p captures, mean absolute RGB
channel differences from the browser's software control were about 7.33–7.40
on a 0–255 scale. These are failures of pixel equivalence, not a passing tolerance.
Large edge differences also include differences in chroma sampling.

The installed Chromium revision's `NativePixmapEGLBinding` explicitly selects
`EGL_ITU_REC601_EXT` for non-BT.2020 NV12 imports, with a comment about matching
its overlay path. This is consistent with the observed BT.709 color shift;
fixing color management requires investigation of Chromium compositing/overlay
behavior, not rewriting correctly decoded YUV pixels in this VA-API driver.
No Chromium binary patch was built or tested here.

## Reproduce the synthetic pixel test

Use a throwaway clone of the pinned external driver, apply the patch, then build
without installing it system-wide:

```sh
git checkout cac6ece0e23ac1f944dd3af266680aff0c3184df
patch -p1 < /path/to/libva-v4l2-request-preexport-dmabuf.patch
meson setup build-preexport
meson compile -C build-preexport
```

Run a nested compositor from the ordinary desktop user's terminal (Weston must
be installed); stop it after testing:

```sh
weston --backend=x11 --renderer=gl --width=960 --height=540 \
  --socket=opi-vaapi-wayland --idle-time=0 --no-config
```

Generate synthetic media with FFmpeg; this reproduces the 1080p fixture. For the
720p baseline variant use `1280x720`, 180 frames and `-preset ultrafast`:

```sh
ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=30 -frames:v 300 -an \
  -vf scale=in_color_matrix=bt601:out_color_matrix=bt709 \
  -c:v libx264 -threads 2 -preset veryfast -crf 23 -pix_fmt yuv420p \
  -color_range tv -colorspace bt709 -color_trc bt709 -color_primaries bt709 \
  -movflags +faststart test-tagged-1080p.mp4
```

The [pixel harness](zero2w-browser-pixels.py) requires `python3-websocket`. Run it
as the desktop user, with a **new** output directory for every trial:

```sh
WAYLAND_DISPLAY=opi-vaapi-wayland python3 zero2w-browser-pixels.py \
  --media /absolute/path/test-tagged-1080p.mp4 --output /absolute/path/new-hw-run \
  --driver /absolute/path/build-preexport/src --preexport
WAYLAND_DISPLAY=opi-vaapi-wayland python3 zero2w-browser-pixels.py \
  --media /absolute/path/test-tagged-1080p.mp4 --output /absolute/path/new-sw-run \
  --software
```

The harness starts an HTTP server bound to loopback, supports byte ranges for
seeking, uses a disposable profile and ephemeral DevTools port, and terminates
its browser process group on completion/deadline. It records events, commands,
playback counters, last frame, seek frames and a page screenshot. Exit zero
means capture completed; `qualified` remains false until separate comparison.
Never equate a nonuniform picture with byte-exact decoder correctness.

No sandbox-disabling flags were supplied. Earlier CDP observations reported the
GPU process as unsandboxed in this GLES environment; full browser sandbox
qualification remains separate. The experiments do not recommend browsing
arbitrary sites with an unreviewed driver or enabling this recipe by default.

## Evidence and next work

[Selected evidence](evidence/2026-10-26/browser-wayland/) contains normalized
summaries/logs and synthetic images. The raw archive is retained privately off
the SD card at `backups/zero2w-browser-wayland-20261026/evidence.tar.gz` in the
parent workspace. It excludes browser profiles and personal files. The real
YouTube screenshot is retained privately, not added to the source repository.

Two early harness mistakes are retained as non-acceptance trials: one browser
started before the experimental driver build completed; another HTTP server
lacked byte ranges, so requested seeks returned time zero. The committed harness
checks that the driver exists and that every seek reaches its requested time.

Next: fix/qualify BT.709 output, measure frame pacing with controlled conditions,
verify longer playback/audio/adaptive streams, test DMA-BUF failure/reuse paths,
and package an explicit experimental option with rollback. Normal XFCE/X11
output negotiation still needs its own solution; nested Weston is a diagnostic
setup, not a replacement desktop integration.

Primary references, pinned to installed Chromium revision
`1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775`:

- [Decoder selection priority](https://chromium.googlesource.com/chromium/src/+/1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775/media/filters/decoder_selector.cc)
- [VA surface allocation and cached frame output](https://chromium.googlesource.com/chromium/src/+/1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775/media/gpu/vaapi/vaapi_video_decoder.cc)
- [NV12 EGL color matrix selection](https://chromium.googlesource.com/chromium/src/+/1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775/ui/ozone/common/native_pixmap_egl_binding.cc)
- [Linux renderable formats](https://chromium.googlesource.com/chromium/src/+/1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775/media/mojo/services/gpu_mojo_media_client_linux.cc)
- [Kernel DMA-BUF import API](https://docs.kernel.org/userspace-api/media/v4l/dmabuf.html)
- [Stateless decoder buffer/reference contract](https://docs.kernel.org/userspace-api/media/v4l/dev-stateless-decoder.html)
