#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Bounded Chromium experiment; run as a desktop user, never root.

Requires python3-websocket and an existing X11/Wayland session. Saves decoder
events AND actual video pixels; a decoder name alone is not a passing result.
The output directory must be new. It contains a disposable browser profile:
archive selected evidence, not the profile, for publication.
"""

import argparse
import base64
import functools
import http.server
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import urllib.request

import websocket


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_head(self):
        # Chromium needs HTTP byte ranges for reliable seeking. A plain
        # SimpleHTTPRequestHandler may silently send it back to time zero.
        if self.path != "/clip.mp4":
            return super().send_head()
        source = open(Path(self.directory) / "clip.mp4", "rb")
        size = os.fstat(source.fileno()).st_size
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
            if not match or int(match[1]) >= size:
                source.close()
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None
            start = int(match[1])
            end = min(int(match[2]), end) if match[2] else end
            if end < start:
                source.close()
                self.send_error(416)
                return None
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        source.seek(start)
        self.remaining = end - start + 1
        return source

    def copyfile(self, source, outputfile):
        if self.path != "/clip.mp4":
            return super().copyfile(source, outputfile)
        while self.remaining:
            chunk = source.read(min(self.remaining, 65536))
            if not chunk:
                break
            outputfile.write(chunk)
            self.remaining -= len(chunk)


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=2, suppress_origin=True)
        self.events = []
        self.ident = 0

    def call(self, method, params=None):
        self.ident += 1
        self.ws.send(json.dumps({"id": self.ident, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if "method" in message:
                self.events.append(message)
            if message.get("id") == self.ident:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message["result"]
        raise TimeoutError(method)

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", type=Path, required=True, help="Synthetic MP4 file")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
    parser.add_argument("--driver", type=Path, help="External libva driver directory")
    parser.add_argument("--preexport", action="store_true", help="Enable experimental DMA-BUF patch")
    parser.add_argument("--software", action="store_true")
    parser.add_argument("--wayland-overlay-delegation", action="store_true", help="Experimental Wayland compositor video delegation")
    parser.add_argument("--driver-trace", action="store_true", help="Trace VA driver buffer timing; affects performance")
    parser.add_argument("--backend", choices=("x11", "wayland"), default="wayland")
    parser.add_argument("--chromium", default="/usr/lib/chromium/chromium")
    parser.add_argument("--timeout", type=int, default=90, help="Overall deadline, seconds")
    parser.add_argument("--warmup", type=float, default=5, help="Seconds excluded from steady-playback counters")
    parser.add_argument("--seeks", default="1,3,5", help="Capture these timestamps after playback")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Run as the desktop user; do not disable Chromium's sandbox to run as root")
    if args.wayland_overlay_delegation and args.backend != "wayland":
        parser.error("--wayland-overlay-delegation requires --backend wayland")
    if args.preexport and (not args.driver or args.software):
        parser.error("--preexport requires --driver and hardware decoding")
    if args.timeout <= 0 or args.warmup < 0:
        parser.error("--timeout must be positive and --warmup nonnegative")
    media = args.media.resolve(strict=True)
    out = args.output.resolve()
    if args.driver and not (args.driver / "v4l2_request_drv_video.so").is_file():
        parser.error("Driver build is missing; complete the build before starting a trial")
    seeks = [float(value) for value in args.seeks.split(",") if value]
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    webroot = out / "web"
    webroot.mkdir()
    (webroot / "clip.mp4").symlink_to(media)
    (webroot / "index.html").write_text(
        '<!doctype html><title>Synthetic decoder validation</title>'
        '<video id="video" src="clip.mp4" width="800" height="450" controls muted></video>'
    )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(webroot))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = os.environ.copy()
    # Isolate driver selection from the caller's previous experiments.
    for name in ("LIBVA_DRIVERS_PATH", "LIBVA_DRIVER_NAME", "LIBVA_TRACE",
                 "LIBVA_V4L2_TRACE", "LIBVA_V4L2_REQUEST_MEDIA_PATH", "V4L2R_PREEXPORT_DMABUF"):
        env.pop(name, None)
    if args.driver:
        env.update(LIBVA_DRIVERS_PATH=str(args.driver.resolve()),
                   LIBVA_DRIVER_NAME="v4l2_request", LIBVA_V4L2_REQUEST_MEDIA_PATH="/dev/media0")
    if args.preexport:
        env["V4L2R_PREEXPORT_DMABUF"] = "1"
    if args.driver_trace:
        env["LIBVA_V4L2_TRACE"] = "1"
    profile = out / "profile"
    cmd = [args.chromium, f"--user-data-dir={profile}", "--no-first-run",
           "--no-default-browser-check", "--remote-debugging-address=127.0.0.1",
           "--remote-debugging-port=0", "--autoplay-policy=no-user-gesture-required",
           "--use-gl=angle", "--use-angle=gles", f"--ozone-platform={args.backend}",
           "--enable-logging=stderr", "--vmodule=*vaapi*=2,*video_decoder*=2"]
    features = ["WaylandOverlayDelegation"] if args.wayland_overlay_delegation else []
    if args.software:
        cmd.append("--disable-accelerated-video-decode")
    else:
        features += ["AcceleratedVideoDecoder", "AcceleratedVideoDecodeLinuxGL",
                     "AcceleratedVideoDecodeLinuxZeroCopyGL"]
        cmd += ["--disable-features=PreferV4L2VideoAcceleration",
                "--hardware-video-device-path=/dev/dri/renderD128"]
    if features:
        cmd.append("--enable-features=" + ",".join(features))
    cmd.append("about:blank")
    (out / "command.json").write_text(json.dumps(cmd, indent=2))
    result = {"media": str(media), "preexport": args.preexport, "software": args.software,
              "backend": args.backend, "driver_trace": args.driver_trace,
              "wayland_overlay_delegation": args.wayland_overlay_delegation, "captures": [], "qualified": False}
    process = None
    cdp = None

    def expired(_signum, _frame):
        raise TimeoutError("overall experiment deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.timeout)
    try:
        with (out / "chromium.log").open("w") as log:
            process = subprocess.Popen(cmd, env=env, stdout=log, stderr=log, start_new_session=True)
        port_file = profile / "DevToolsActivePort"
        while not port_file.exists():
            if process.poll() is not None:
                raise RuntimeError(f"Chromium exited: {process.returncode}")
            time.sleep(0.2)
        port = int(port_file.read_text().splitlines()[0])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
            tabs = json.load(response)
        cdp = CDP(next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"))
        cdp.call("Media.enable")
        cdp.call("Page.enable")
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/index.html"})
        while not cdp.evaluate("!!document.querySelector('video') && video.readyState >= 2"):
            time.sleep(0.2)
        cdp.evaluate("video.play()")
        playback_started = time.monotonic()
        samples = []
        warm_sample = None
        while True:
            state = cdp.evaluate("({time:video.currentTime,duration:video.duration,ended:video.ended,"
                                 "error:video.error && {code:video.error.code,message:video.error.message},"
                                 "totalFrames:video.getVideoPlaybackQuality().totalVideoFrames,"
                                 "droppedFrames:video.getVideoPlaybackQuality().droppedVideoFrames})")
            state["elapsed"] = time.monotonic() - playback_started
            samples.append(state)
            if warm_sample is None and state["time"] >= args.warmup and not state["ended"]:
                warm_sample = state
            if state["error"]:
                raise RuntimeError(state["error"])
            if state["ended"]:
                break
            time.sleep(0.5)
        result["playback"] = state
        result["samples"] = samples
        if warm_sample:
            result["steady_playback"] = {
                "from_media_time": warm_sample["time"], "to_media_time": state["time"],
                "wall_seconds": state["elapsed"] - warm_sample["elapsed"],
                "totalFrames": state["totalFrames"] - warm_sample["totalFrames"],
                "droppedFrames": state["droppedFrames"] - warm_sample["droppedFrames"],
            }

        def capture(label):
            data = cdp.evaluate("(()=>{const c=document.createElement('canvas');c.width=video.videoWidth;"
                                "c.height=video.videoHeight;c.getContext('2d').drawImage(video,0,0);"
                                "return {time:video.currentTime,png:c.toDataURL('image/png')}})()")
            (out / f"{label}.png").write_bytes(base64.b64decode(data["png"].split(",", 1)[1]))
            result["captures"].append({"file": f"{label}.png", "time": data["time"]})

        capture("last-frame")
        for timestamp in seeks:
            if not 0 <= timestamp < state["duration"]:
                raise ValueError(f"Seek {timestamp} outside clip duration")
            cdp.evaluate("new Promise((resolve,reject)=>{video.pause();"
                         "video.addEventListener('seeked',()=>resolve(true),{once:true});"
                         f"video.currentTime={json.dumps(timestamp)};" + "})")
            actual = cdp.evaluate("video.currentTime")
            if abs(actual - timestamp) > 1 / 30:
                raise RuntimeError(f"Seek requested {timestamp}, reached {actual}")
            capture(f"seek-{timestamp:g}")
        shot = cdp.call("Page.captureScreenshot", {"format": "png"})
        (out / "page.png").write_bytes(base64.b64decode(shot["data"]))
        result["properties"] = {}
        for event in cdp.events:
            if event.get("method") == "Media.playerPropertiesChanged":
                for prop in event["params"]["properties"]:
                    result["properties"][prop["name"]] = prop["value"]
        result["capture_complete"] = True
        # Pixel correctness requires a separate reference comparison; this script
        # intentionally never labels decoder selection/counters as qualification.
    except Exception as error:
        result["error"] = repr(error)
    finally:
        signal.alarm(0)
        if cdp:
            cdp.ws.close()
            (out / "events.json").write_text(json.dumps(cdp.events, indent=2))
        if process:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        (out / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    return 0 if result.get("capture_complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
