# Browser / DMA-BUF evidence

See the [report](../../../zero2w-browser-wayland-2026-10-26.md).
`summary.json` separates early diagnostics, invalid harness trials and final-patch
runs. Decoder selection history is retained so a VA-API attempt followed by
software fallback cannot be mistaken for accelerated playback.

- `unpatched-green.png`: actual canvas capture with unmodified bridge; one RGB color.
- `patched-1080p.png`, `software-1080p.png`: actual final frames of the same tagged
  synthetic H.264 clip. Hardware output contains the picture, but colors fail
  equivalence; the summary records numerical differences and seek comparisons.
- Selected Chromium logs show X11 fallback, Wayland NV12 negotiation, Cedrus
  selection and the experimental imported-backing path.
- `youtube-decoder.log`: only decoder-related lines from the live YouTube trial.
  The private archive retains full events and a screenshot. No page body,
  recommendations, cookies, personal profiles or media downloads are published.
- Provenance and cleanup files record exact packages, checksums and stopped
  diagnostic services. Runtime test paths/debugger addresses are normalized.

The final patch and pixel harness published with the report are byte-identical
to their tested copies in the raw archive. The final binary hash identifies an
experimental build, not a signed package or a production acceptance result.
Early patched probes used earlier iterations; use the `*-v3` cases for final
synthetic results. The YouTube trial also used the final driver build.
