#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded YouTube trial using a fresh profile and the opt-in H.264 extension.

Requires python3-websocket and the sibling pixel harness.
Run as a desktop user in Wayland. Output is private: publish selected counters,
not browser profiles or full Media events. Decoder selection alone is not a pass.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

spec = importlib.util.spec_from_file_location("pixels", Path(__file__).with_name("zero2w-browser-pixels.py"))
pixels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pixels)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--driver', type=Path, required=True)
    ap.add_argument('--extension', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--native-codecs', action='store_true', help='Software control without the H.264 extension')
    ap.add_argument('--software', action='store_true', help='Control run with CPU video decode')
    ap.add_argument('--warmup', type=int, default=15, help='Minimum playing seconds before measurement')
    ap.add_argument('--audio', action='store_true', help='Unmute video; does not prove audible output or A/V sync')
    args = ap.parse_args()
    if os.geteuid() == 0 or not 10 <= args.seconds <= 180 or not 5 <= args.warmup <= 60:
        ap.error('Use the desktop user, duration 10–180 seconds and warm-up 5–60 seconds')
    if args.native_codecs and not args.software:
        ap.error('--native-codecs is only a software control')
    driver = args.driver.resolve(strict=True)
    extension = args.extension.resolve(strict=True)
    if not (driver/'v4l2_request_drv_video.so').is_file() or not (extension/'manifest.json').is_file():
        ap.error('Driver or extension missing')
    out = args.output.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = os.environ.copy()
    for name in ('LIBVA_TRACE', 'LIBVA_V4L2_TRACE'):
        env.pop(name, None)
    env.update(LIBVA_DRIVERS_PATH=str(driver), LIBVA_DRIVER_NAME='v4l2_request',
               LIBVA_V4L2_REQUEST_MEDIA_PATH='/dev/media0', V4L2R_PREEXPORT_DMABUF='1')
    cmd = ['/usr/lib/chromium/chromium', f'--user-data-dir={out / "profile"}',
           '--no-first-run', '--no-default-browser-check', '--remote-debugging-address=127.0.0.1',
           '--remote-debugging-port=0', '--autoplay-policy=no-user-gesture-required',
           '--use-gl=angle', '--use-angle=gles', '--ozone-platform=wayland',
           '--enable-features=AcceleratedVideoDecoder,AcceleratedVideoDecodeLinuxGL,AcceleratedVideoDecodeLinuxZeroCopyGL',
           '--disable-features=PreferV4L2VideoAcceleration', '--hardware-video-device-path=/dev/dri/renderD128',
           f'--load-extension={extension}', f'--disable-extensions-except={extension}',
           '--enable-logging=stderr', '--vmodule=*vaapi*=2,*video_decoder*=2', 'about:blank']
    if args.software:
        cmd = [arg for arg in cmd if not arg.startswith('--enable-features=')]
        cmd.insert(-1, '--disable-accelerated-video-decode')
        for name in ('LIBVA_DRIVERS_PATH', 'LIBVA_DRIVER_NAME', 'LIBVA_V4L2_REQUEST_MEDIA_PATH', 'V4L2R_PREEXPORT_DMABUF'):
            env.pop(name, None)
    if args.native_codecs:
        cmd = [arg for arg in cmd if not arg.startswith(('--load-extension=', '--disable-extensions-except='))]
    (out/'command.json').write_text(json.dumps(cmd, indent=2))
    result = {'qualified': False, 'audio_requested': args.audio, 'software': args.software, 'native_codecs': args.native_codecs, 'samples': [], 'warmup_samples': [], 'warmup_min_seconds': args.warmup}
    proc = cdp = None
    def expired(*_):
        raise TimeoutError('YouTube test deadline')
    def interrupted(*_):
        raise InterruptedError('YouTube test interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.seconds + args.warmup + 130)
    try:
        with (out/'chromium.log').open('w') as log:
            proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=log, start_new_session=True)
        port_file = out/'profile/DevToolsActivePort'
        while not port_file.exists():
            if proc.poll() is not None:
                raise RuntimeError(f'Chromium exited: {proc.returncode}')
            time.sleep(.2)
        port = int(port_file.read_text().splitlines()[0])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as response:
            tabs = json.load(response)
        cdp = pixels.CDP(next(t['webSocketDebuggerUrl'] for t in tabs if t['type'] == 'page'))
        cdp.call('Runtime.enable')
        cdp.call('Network.enable')
        cdp.call('Media.enable')
        cdp.call('Page.enable')
        cdp.call('Page.navigate', {'url': 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'})
        deadline = time.monotonic() + 65
        while not cdp.evaluate('!!document.querySelector("#movie_player video.html5-main-video") && document.querySelector("#movie_player video.html5-main-video").readyState >= 2'):
            if time.monotonic() > deadline:
                raise RuntimeError('No ready video: check network, consent or player state manually')
            time.sleep(1)
        result['codec_negotiation'] = cdp.evaluate('({h264:MediaSource.isTypeSupported(\'video/mp4; codecs="avc1.640028"\'),vp9:MediaSource.isTypeSupported(\'video/webm; codecs="vp09.00.51.08"\'),av1:MediaSource.isTypeSupported(\'video/mp4; codecs="av01.0.08M.08"\')})')
        if not args.native_codecs and result['codec_negotiation'] != {'h264': True, 'vp9': False, 'av1': False}:
            raise RuntimeError('H.264 extension is not active')
        cdp.evaluate('(()=>{const v=document.querySelector("#movie_player video.html5-main-video");v.muted=' + ('false' if args.audio else 'true') + ';v.volume=0.25;return v.play()})()')
        snapshot = """(()=>{const p=document.querySelector('#movie_player'),v=p?.querySelector('video.html5-main-video');
          if(!v)return {missing:true};const q=v.getVideoPlaybackQuality();
          let ahead=0;for(let i=0;i<v.buffered.length;i++)if(v.buffered.start(i)<=v.currentTime&&v.buffered.end(i)>=v.currentTime)ahead=v.buffered.end(i)-v.currentTime;
          return {time:v.currentTime,width:v.videoWidth,height:v.videoHeight,paused:v.paused,ready:v.readyState,
          muted:v.muted,visibility:document.visibilityState,adShowing:p.classList.contains('ad-showing'),bufferedAhead:ahead,
          error:v.error&&{code:v.error.code,message:v.error.message},totalFrames:q.totalVideoFrames,droppedFrames:q.droppedVideoFrames}})()"""
        warm_started = time.monotonic()
        first_media = None
        stable = 0
        previous_size = None
        while True:
            state = cdp.evaluate(snapshot)
            state['elapsed'] = time.monotonic()-warm_started
            result['warmup_samples'].append(state)
            if state.get('error'):
                raise RuntimeError(state['error'])
            valid = (not state.get('missing') and not state['paused'] and state['ready'] >= 3
                     and state['width'] > 0 and not state['adShowing'] and state['visibility'] == 'visible')
            if valid:
                if first_media is None:
                    first_media = state['time']
                size = (state['width'], state['height'])
                stable = stable+1 if size == previous_size else 1
                previous_size = size
                if (state['elapsed'] >= args.warmup and state['time']-first_media >= args.warmup
                        and stable >= 3 and state['bufferedAhead'] >= 2):
                    break
            else:
                stable = 0
                first_media = None
            if state['elapsed'] > args.warmup + 45:
                raise RuntimeError('Video did not reach stable, buffered playback during warm-up')
            time.sleep(1)
        baseline = dict(state)
        baseline['elapsed'] = 0
        result['samples'].append(baseline)
        start = time.monotonic()
        while True:
            time.sleep(1)
            state = cdp.evaluate(snapshot)
            state['elapsed'] = time.monotonic()-start
            result['samples'].append(state)
            if state.get('missing') or state.get('error'):
                raise RuntimeError('Main video disappeared or reported a media error')
            previous = result['samples'][-2]
            if (state['totalFrames'] < previous['totalFrames'] or state['droppedFrames'] < previous['droppedFrames']
                    or state['time'] < previous['time']-0.1 or state['adShowing']):
                raise RuntimeError('Video reset, seek or advertisement invalidated the measurement window')
            if state['elapsed'] >= args.seconds:
                break
        total = state['totalFrames']-baseline['totalFrames']
        dropped = state['droppedFrames']-baseline['droppedFrames']
        result['measurement'] = {
            'warmup_wall_seconds': result['warmup_samples'][-1]['elapsed'],
            'from_media_time': baseline['time'], 'to_media_time': state['time'],
            'wall_seconds': state['elapsed'], 'totalFrames': total, 'droppedFrames': dropped,
            'drop_percent': 100*dropped/total if total else None,
            'resolution_changes': sum((a['width'],a['height']) != (b['width'],b['height'])
                                      for a,b in zip(result['samples'],result['samples'][1:])),
            'paused_or_unready_samples': sum(t['paused'] or t['ready'] < 3 for t in result['samples']),
        }
        if total <= 0:
            raise RuntimeError('No decoded frames during measurement')
        shot = cdp.call('Page.captureScreenshot', {'format': 'png'})
        (out/'page.png').write_bytes(base64.b64decode(shot['data']))
        result['capture_complete'] = True
    except Exception as error:
        result['error'] = repr(error)
        if cdp:
            try:
                shot = cdp.call('Page.captureScreenshot', {'format': 'png'})
                (out/'failure-page.png').write_bytes(base64.b64decode(shot['data']))
            except Exception:
                pass
    finally:
        signal.alarm(0)
        if cdp:
            try:
                result['playability'] = cdp.evaluate("(()=>{const s=document.querySelector('#movie_player')?.getPlayerResponse?.()?.playabilityStatus;return s?{status:s.status,reason:s.reason}:null})()")
            except Exception:
                pass
            (out/'events.json').write_text(json.dumps(cdp.events, indent=2))
            players = {}
            for event in cdp.events:
                if event.get('method') == 'Media.playerPropertiesChanged':
                    params = event['params']
                    players.setdefault(params['playerId'], {}).update({p['name']:p['value'] for p in params['properties']})
            result['players'] = players
            cdp.ws.close()
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        (out/'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples', 'warmup_samples', 'players')}, indent=2))
    if result['samples']:
        print(json.dumps({'first':result['samples'][0],'last':result['samples'][-1]}, indent=2))
    return 0 if result.get('capture_complete') else 1


if __name__ == '__main__':
    raise SystemExit(main())
