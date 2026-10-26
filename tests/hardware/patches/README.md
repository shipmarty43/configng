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
