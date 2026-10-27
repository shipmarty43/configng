# Resumed hardware/browser evidence

See the [report](../../../zero2w-browser-direct-2026-10-27.md).

- Synthetic JSON files preserve playback samples and decoder properties. Paths
  and loopback addresses are normalized or omitted. Atomic-KMS output is marked
  invalid for physical-display acceptance despite zero dropped-frame counters.
- `summary.json` compares the synthetic runs; `driver-timing.json` summarizes a
  short traced run separately from untraced performance measurements.
- `youtube-automated-summary.json` retains failure classifications and warm-up
  boundaries. No uninterrupted 90-second YouTube pass is claimed from these runs.
  The separate manual user observation is documented in the report.
- Weston extracts retain renderer/output/error evidence, omitting device identifiers.
- `performance-recovered.json` recovers the pre-outage CPU performance experiment.
- `egl-yuv-color-final.log` records the final source rerun, unlike the older log
  that predates the additional descriptor assertions.

Private off-SD archives exclude profiles and temporary HTTP directories:

- `resumed-stage1.tar.gz`: SHA-256
  `870f59cc9d1a143cd088e2bb9fbc2d9249fe46110d2f608e00a53d79944aa2cd`
- `resumed-automated.tar.gz`: SHA-256
  `85458a27c9d60e3fff4b6f942cb2cceb79afd7770fcb716b9ba1544bd029e31f`

These raw archives stay in the local backups directory. Do not publish private
browser profiles, full network events/signed URLs, or YouTube page screenshots.
