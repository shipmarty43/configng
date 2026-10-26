#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Use an explicitly selected, separately built libva-v4l2_request driver.
# Synthetic media only; no installation or persistent environment changes.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 /absolute/path/to/driver/build/src [results-parent]" >&2
    exit 2
fi
driver_dir=$(realpath "$1")
test -f "$driver_dir/v4l2_request_drv_video.so"
result_dir=$(mktemp -d "${2:-/tmp}/zero2w-vaapi.XXXXXX")
printf 'Results: %s\n' "$result_dir"
cd "$result_dir"
export LIBVA_DRIVERS_PATH="$driver_dir"
export LIBVA_DRIVER_NAME=v4l2_request
export LIBVA_V4L2_REQUEST_MEDIA_PATH=/dev/media0
timeout 25 vainfo --display drm --device /dev/dri/renderD128 > vainfo.txt 2>&1
ffmpeg -v error -f lavfi -i testsrc2=size=320x240:rate=30 -frames:v 60 \
    -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p test.h264
timeout 30 ffmpeg -v verbose -hwaccel vaapi \
    -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi \
    -i test.h264 -vf hwdownload,format=nv12 -f rawvideo hardware.nv12 \
    > decode.txt 2>&1
# hwdownload requires actual hardware surfaces; a software frame cannot pass it.
# Also require this driver's Cedrus selection, not another installed decoder.
grep -Ei 'decoding h264.*\[cedrus\]' decode.txt
ffmpeg -v error -hwaccel none -i test.h264 -pix_fmt nv12 -f rawvideo reference.nv12
test "$(stat -c %s hardware.nv12)" -eq 6912000
test "$(stat -c %s reference.nv12)" -eq 6912000
cmp hardware.nv12 reference.nv12
sha256sum test.h264 hardware.nv12 reference.nv12 > SHA256SUMS
echo 'PASS: Cedrus VA-API H.264, 60 frames 320x240 NV12, byte-exact software comparison'
