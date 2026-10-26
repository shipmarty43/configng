#!/bin/bash
set -euo pipefail
# Synthetic clips only. Requires ffmpeg, gst-launch-1.0, v4l2codecs and parsers.
# Each run gets a fresh directory; no existing media are overwritten.
result_dir=$(mktemp -d "${1:-/tmp}/zero2w-codecs.XXXXXX")
printf 'Results: %s\n' "$result_dir"
cd "$result_dir"
mkdir logs media-tests
run_codec() {
    local name=$1 encoder=$2 parser=$3 decoder=$4
    shift 4
    ffmpeg -v error -f lavfi -i testsrc2=size=320x240:rate=30 -t 2 -an -c:v "$encoder" "$@" -y "media-tests/$name"
    ffmpeg -v error -i "media-tests/$name" -pix_fmt yuv420p -f rawvideo -y "media-tests/$name.software.yuv"
    GST_DEBUG=2 timeout 30 gst-launch-1.0 -q filesrc location="media-tests/$name" ! "$parser" ! "$decoder" ! videoconvert ! video/x-raw,format=I420 ! filesink location="media-tests/$name.hardware.yuv" > "logs/codec-$name.txt" 2>&1
    echo "$name: hardware pipeline reached EOS"
}
run_codec test.h264 libx264 h264parse v4l2slh264dec -preset ultrafast -pix_fmt yuv420p
run_codec test.h265 libx265 h265parse v4l2slh265dec -preset ultrafast -pix_fmt yuv420p -x265-params pools=1:frame-threads=1:log-level=error
run_codec test.m2v mpeg2video mpegvideoparse v4l2slmpeg2dec -pix_fmt yuv420p
# VP8 uses an IVF container and the IVF demuxer before the stateless decoder.
run_codec test.ivf libvpx ivfparse v4l2slvp8dec -deadline realtime -cpu-used 5 -pix_fmt yuv420p
python3 - <<'PY'
from pathlib import Path
for p in Path('media-tests').glob('*.software.yuv'):
    hardware=Path(str(p).replace('.software.yuv','.hardware.yuv'))
    a=p.read_bytes(); b=hardware.read_bytes()
    assert len(a)==len(b)==60*320*240*3//2, (p.name,len(a),len(b))
    mse=sum((x-y)**2 for x,y in zip(a,b))/len(a)
    maxdiff=max(abs(x-y) for x,y in zip(a,b))
    print(f'{p.name}: 60 decoded frames, mean squared error={mse:.6f}, max difference={maxdiff}')
    assert mse < 4, 'Hardware output differs substantially from software reference'
PY
