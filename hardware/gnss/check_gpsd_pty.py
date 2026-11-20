"""Feed a real gpsd daemon synthetic UART NMEA through a Linux PTY."""
import argparse
from datetime import datetime, timezone
import os
import pty
import queue
import socket
import subprocess
import threading
import time

import opi_gnss
from test_gnss import sentence


def check(binary):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        address = reserve.getsockname()
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    samples = queue.Queue()
    def read():
        try:
            opi_gnss.watch_gpsd(device, lambda *sample: samples.put(sample), address)
        except (ConnectionError, OSError):
            pass
    try:
        with subprocess.Popen([binary,'-N','-n','-b','-s','9600','-S',str(address[1]),device]) as daemon:
            try:
                deadline = time.monotonic()+12
                while True:
                    try:
                        with socket.create_connection(address, timeout=.2):
                            break
                    except OSError:
                        if daemon.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError('gpsd failed to listen')
                        time.sleep(.05)
                thread = threading.Thread(target=read, daemon=True)
                thread.start()
                while time.monotonic() < deadline:
                    now = datetime.now(timezone.utc)
                    clock = now.strftime('%H%M%S.%f')
                    payloads = (f'GPRMC,{clock},A,5027.000,N,03030.000,E,0,0,{now:%d%m%y},,,A',
                                f'GPGGA,{clock},5027.000,N,03030.000,E,1,08,1.0,150.0,M,0.0,M,,')
                    for body in payloads:
                        os.write(master, (sentence(body)+'\r\n').encode())
                    try:
                        state, fix = samples.get(timeout=.25)
                    except queue.Empty:
                        continue
                    if state=='fix' and abs(time.time()-fix['time'])<3 and abs(fix['lat']-50.45)<1e-5 and abs(fix['lon']-30.5)<1e-5:
                        print('PASS: PTY UART -> real gpsd -> timestamped Waveshare fix')
                        return
                raise AssertionError('No fresh fix on the selected GPSD device')
            finally:
                daemon.terminate()
    finally:
        os.close(slave)
        os.close(master)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gpsd')
    check(parser.parse_args().gpsd)
