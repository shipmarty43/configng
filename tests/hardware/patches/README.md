# External-driver experiments

`libva-v4l2-request-preexport-dmabuf.patch` applies to Ondrej Jirman's
libva-v4l2_request commit `cac6ece0e23ac1f944dd3af266680aff0c3184df`.
It modifies GPL-3.0-or-later external driver code and is supplied under that
license; it is not part of the configng executable. Preserve the upstream
copyright and license notices when applying or redistributing the driver.

The patch is opt-in, limited to the H.264/NV12 pre-export path, and experimental.
See the [board report](../zero2w-browser-wayland-2026-10-26.md) for build/run
instructions, passing observations, remaining failures and integration limits.
Do not install it globally or advertise general hardware browser support based
only on a successful build, decoder selection or advancing frame counters.

## Chromium color-import draft

`chromium-wayland-bt709-egl-import-draft.patch` targets Chromium revision
`1d17a2e2ee147bb7d6ae2ab6abdb3a2510c17775`, file
`ui/ozone/common/native_pixmap_egl_binding.cc`. Preserve Chromium's upstream
BSD-style license notices. This is a separate browser experiment, not configng code.

The proposed `WaylandBt709EglImport` feature defaults off. After a successful
build, an experimental invocation would add it to `--enable-features` together
with explicit `--ozone-platform=wayland`; Wayland overlay delegation must remain
disabled. Other matrices, ranges and normal defaults are unchanged.

**Not compiled, installed or verified in Chromium.** The standalone EGL matrix
pass does not qualify this patch. See the [follow-up report](../zero2w-browser-followup-2026-10-27.md)
for evidence, build constraints and required end-to-end tests.
