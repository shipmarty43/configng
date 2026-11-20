#!/usr/bin/env python3
"""Local GNSS selection for the Orange Pi Zero 2W."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
from functools import reduce
import json
import math
import operator
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time

CONFIG = Path('/etc/opi-gnss.json')
SNAPSHOT = Path('/run/opi-gnss/status.json')
SOURCES = ('waveshare', 'modem')
MODES = ('off', 'auto', *SOURCES)
DEFAULTS = dict(mode='off', prefer='waveshare', device='')
MAX_AGE = 10
RECOVERY = 15


def atomic_json(path, data, mode):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode='w') as stream:
        tmp = Path(stream.name)
        try:
            json.dump(data, stream, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            if path == CONFIG:
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def config(path):
    data = DEFAULTS | (json.loads(path.read_text()) if path.exists() else {})
    if (data.keys() != DEFAULTS.keys() or data['mode'] not in MODES or data['prefer'] not in SOURCES
            or not isinstance(data['device'], str) or (data['device'] and not re.fullmatch(r'/dev/[\w./-]+', data['device']))):
        raise ValueError('Invalid GNSS configuration')
    return data


def position(timestamp, latitude, longitude, **quality):
    if not all(math.isfinite(v) for v in (timestamp, latitude, longitude)):
        raise ValueError('Non-finite fix')
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('Coordinate out of bounds')
    return dict(time=timestamp, lat=latitude, lon=longitude, **quality)


def gpsd_fix(report):
    if report.get('mode') not in (2, 3) or report.get('status') in (6, 8, 9):  # estimated / dead reckoning
        return None
    if 'time' not in report or 'lat' not in report or 'lon' not in report:
        return None
    utc = datetime.fromisoformat(report['time'].replace('Z', '+00:00'))
    if utc.tzinfo is None:
        raise ValueError('GPSD timestamp requires a UTC offset')
    quality = {'dimension': report['mode']}
    for field in ('eph', 'epx', 'epy'):
        value = report.get(field)
        if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            quality[field] = value
    return position(utc.timestamp(), report['lat'], report['lon'], **quality)


def rmc(line):
    body, star, checksum = line.strip().partition('*')
    if not re.fullmatch(r'\$[A-Z]{2}RMC,.*', body):
        return None
    if not star or not re.fullmatch(r'[0-9a-fA-F]{2}', checksum) or reduce(operator.xor, body[1:].encode('ascii'), 0) != int(checksum, 16):
        raise ValueError('Bad RMC checksum')
    fields = body.split(',')
    if len(fields) < 10 or fields[2] != 'A' or (len(fields)>12 and fields[12] in ('N','E','S','M')):
        return None
    stamp = fields[9] + fields[1]
    utc = datetime.strptime(stamp, '%d%m%y%H%M%S.%f' if '.' in stamp else '%d%m%y%H%M%S').replace(tzinfo=timezone.utc)
    def coordinate(raw, hemisphere, axis):
        width = 2 if axis=='NS' else 3
        if hemisphere not in tuple(axis) or not re.fullmatch(r'\d{' + str(width+2) + r'}(?:\.\d+)?', raw):
            raise ValueError('Invalid RMC coordinate')
        minutes = float(raw[width:])
        if minutes >= 60:
            raise ValueError('Invalid RMC minutes')
        return (int(raw[:width]) + minutes/60) * (1 if hemisphere==axis[0] else -1)
    return position(utc.timestamp(), coordinate(fields[3], fields[4], 'NS'), coordinate(fields[5], fields[6], 'EW'))


def watch_gpsd(device, emit, address=('127.0.0.1', 2947)):
    if not device:
        emit('disabled', None)
        return
    with closing(socket.create_connection(address, timeout=3)) as sock, sock.makefile('rb') as stream:
        # Some persistent /dev aliases exceed the gpsd WATCH command size.
        # Subscribe locally and filter by the exact configured device on receipt.
        sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
        emit('acquiring', None)
        while True:
            line = stream.readline(10241)
            if not line:
                raise ConnectionError('gpsd disconnected')
            if len(line)>10240:
                raise ValueError('Oversized gpsd report')
            msg = json.loads(line)
            if msg.get('class') == 'DEVICES' and not any(d.get('path')==device for d in msg.get('devices', [])):
                emit('absent', None)
            if msg.get('path') == device and msg.get('class') == 'DEVICE' and msg.get('activated') in (0, '0'):
                emit('absent', None)
            if msg.get('class') == 'TPV' and msg.get('device') == device:
                fix = gpsd_fix(msg)
                if fix or msg.get('mode') not in (2, 3) or msg.get('status') in (6, 8, 9):
                    emit('fix' if fix else 'acquiring', fix)


def mmcli(*args):
    data = subprocess.check_output(['mmcli', '-J', *args], timeout=4, stderr=subprocess.DEVNULL)
    return json.loads(data)


def poll_modem(call=mmcli):
    paths = call('-L').get('modem-list', [])
    matches = []
    for path in paths:
        if 'SIM7600' in call('-m',path)['modem']['generic']['model'].upper():
            matches.append(path)
    if not matches:
        return 'absent', None
    if len(matches)!=1:
        return 'ambiguous', None
    target = ('-m', matches[0])
    status = call(*target, '--location-status')['modem']['location']
    if 'gps-nmea' not in status['capabilities']:
        return 'unsupported', None
    if 'gps-nmea' not in status['enabled']:
        return 'disabled', None
    traces = call(*target, '--location-get')['modem']['location']['gps'].get('nmea', [])
    if isinstance(traces, str):
        traces = [traces]
    fixes = [fix for trace in traces for line in trace.splitlines() if (fix := rmc(line))]
    return ('fix', max(fixes, key=lambda f: f['time'])) if fixes else ('acquiring', None)


class Selector:
    def __init__(self, settings):
        self.settings = settings
        self.samples = {k: ('disabled', None) for k in SOURCES}
        self.since = {}
        self.last_measurement = {}
        self.selected = None

    def update(self, name, state, fix, now, monotonic):
        prior = self.last_measurement.get(name)
        if prior and (monotonic-prior[1] > MAX_AGE or not -1 <= now-prior[0] <= MAX_AGE):
            self.since.pop(name, None)
        if fix:
            stamp = fix['time']
            if not -1 <= now-stamp <= MAX_AGE:
                state, fix = 'stale', None
            elif prior and stamp < prior[0]:
                return
            elif prior and stamp == prior[0] and monotonic-prior[1] > MAX_AGE:
                state, fix = 'stale', None
            elif not prior or stamp > prior[0]:
                self.last_measurement[name] = stamp, monotonic
        if fix:
            self.since.setdefault(name, monotonic)
        else:
            self.since.pop(name, None)
        self.samples[name] = state, fix

    def snapshot(self, now, monotonic):
        states, fresh = {}, {}
        for name, (state, fix) in self.samples.items():
            if fix and name in self.since and monotonic-self.last_measurement[name][1] <= MAX_AGE and -1 <= now-fix['time'] <= MAX_AGE:
                fresh[name] = fix
            elif fix:
                state = 'stale'
                self.since.pop(name, None)
            states[name] = {'state': state}
            if fix:
                states[name].update(time=fix['time'], age_seconds=max(0, now-fix['time']))
        mode, pref = self.settings['mode'], self.settings['prefer']
        if mode == 'auto':
            if self.selected not in fresh:
                self.selected = pref if pref in fresh else next(iter(fresh), None)
            elif pref in fresh and monotonic-self.since[pref] >= RECOVERY:
                self.selected = pref
        else:
            self.selected = mode if mode in fresh else None
        return dict(mode=mode, prefer=pref, source=self.selected, fix=fresh.get(self.selected), sources=states, generated=now)


def reader(name, settings, events):
    def emit(state, fix):
        events.put((name, state, fix))
    while True:
        try:
            if name == 'modem':
                emit(*poll_modem())
            else:
                watch_gpsd(settings['device'], emit)
        except (FileNotFoundError, ConnectionRefusedError):
            emit('absent', None)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError):
            emit('error', None)
        time.sleep(2)


def serve(settings, path):
    selected = Selector(settings)
    events = queue.Queue(maxsize=64)
    for name in SOURCES:
        if settings['mode'] in ('auto', name):
            selected.samples[name] = ('acquiring', None)
            threading.Thread(target=reader, args=(name,settings,events), daemon=True).start()
    while True:
        # Bound each batch so a fast receiver cannot starve status publication.
        for _ in range(64):
            try:
                item = events.get_nowait()
            except queue.Empty:
                break
            selected.update(*item, time.time(), time.monotonic())
        atomic_json(path, selected.snapshot(time.time(), time.monotonic()), 0o640)
        time.sleep(0.5)


def read_status(path, now):
    data = json.loads(path.read_text())
    if not -1 <= now-data['generated'] <= MAX_AGE:
        data.update(source=None, fix=None)
        for value in data['sources'].values():
            value['state'] = 'stale'
    for source, value in data['sources'].items():
        if 'time' in value:
            age = now-value['time']
            value['age_seconds'] = max(0, age)
            if not -1 <= age <= MAX_AGE:
                value['state'] = 'stale'
                if data['source']==source:
                    data.update(source=None, fix=None)
    return data


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='action', required=True)
    for action in ('serve', 'status', 'config'):
        sub.add_parser(action)
    change = sub.add_parser('configure')
    change.add_argument('--mode', choices=MODES)
    change.add_argument('--prefer', choices=SOURCES)
    change.add_argument('--device', help='Exact Waveshare UART path used by gpsd')
    args = cli.parse_args()
    if args.action=='configure':
        with CONFIG.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            settings = config(CONFIG)
            for key in DEFAULTS:
                value = getattr(args, key)
                if value is not None:
                    settings[key] = value
            if settings['device'] and not re.fullmatch(r'/dev/[\w./-]+', settings['device']):
                cli.error('Expected a /dev path')
            atomic_json(CONFIG, settings, 0o644)
    elif args.action=='serve':
        serve(config(CONFIG), SNAPSHOT)
    elif args.action=='status':
        data = read_status(SNAPSHOT, time.time()) if SNAPSHOT.exists() else dict(mode=config(CONFIG)['mode'], service='inactive', source=None, fix=None)
        print(json.dumps(data, indent=2))
    else:
        print(json.dumps(config(CONFIG), indent=2))


if __name__=='__main__':
    main()
