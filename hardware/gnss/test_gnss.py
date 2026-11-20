import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import opi_gnss as g


def sentence(body):
    checksum = 0
    for byte in body.encode():
        checksum ^= byte
    return f'${body}*{checksum:02X}'


RMC = sentence('GNRMC,120000.00,A,5027.000,N,03030.000,E,0,0,201126,,,A')


class Adapters(unittest.TestCase):
    def test_nmea(self):
        self.assertEqual(g.rmc(RMC), g.position(1795176000, 50.45, 30.5))
        self.assertIsNone(g.rmc(sentence('GNRMC,120000,V,,,,,,,201126')))
        for invalid in (RMC[:-2]+'00', sentence('GPRMC,120000,A,5061.000,N,03030.000,E,0,0,201126')):
            with self.assertRaises(ValueError):
                g.rmc(invalid)

    def test_gpsd(self):
        msg = dict(mode=3, time='2026-11-20T12:00:00Z', lat=50.45, lon=30.5, eph=2.5)
        self.assertEqual(g.gpsd_fix(msg), dict(g.rmc(RMC), dimension=3, eph=2.5))
        self.assertIsNone(g.gpsd_fix(msg | {'mode':1}))
        self.assertIsNone(g.gpsd_fix(msg | {'status':6}))
        with self.assertRaises(ValueError):
            g.gpsd_fix(msg | {'lon':float('nan')})

    def test_modem(self):
        path = '/org/freedesktop/ModemManager1/Modem/7'
        def call(*args):
            return results[args]
        gps = {'nmea':[RMC]}
        status = {'capabilities':['3gpp-lac-ci','gps-nmea'], 'enabled':['gps-nmea']}
        results = {('-L',): {'modem-list':[path]}, ('-m',path):{'modem':{'generic':{'model':'SIMCOM_SIM7600G-H'}}},
                   ('-m',path,'--location-status'):{'modem':{'location':status}},
                   ('-m',path,'--location-get'):{'modem':{'location':{'gps':gps}}}}
        self.assertEqual(g.poll_modem(call), ('fix', g.rmc(RMC)))
        gps['nmea'] = []
        self.assertEqual(g.poll_modem(call), ('acquiring', None))
        status['enabled'] = ['3gpp-lac-ci']
        self.assertEqual(g.poll_modem(call), ('disabled', None))
        status['capabilities'] = []
        self.assertEqual(g.poll_modem(call), ('unsupported', None))
        results[('-L',)]['modem-list'] = []
        self.assertEqual(g.poll_modem(call), ('absent', None))


class Selection(unittest.TestCase):
    def setUp(self):
        self.s = g.Selector(dict(mode='auto',prefer='waveshare'))
    def put(self,name,now,stamp=None):
        self.s.update(name, 'fix', g.position(now if stamp is None else stamp, 50,30), now, now)
    def chosen(self,now):
        return self.s.snapshot(now,now)['source']
    def test_stale_and_recovery(self):
        self.put('waveshare',10)
        self.assertEqual(self.chosen(10),'waveshare')
        self.put('modem',21)
        self.assertEqual(self.chosen(21),'modem')
        self.put('waveshare',22)
        self.assertEqual(self.chosen(22),'modem')
        for now in (29,36):
            self.put('modem',now)
            self.put('waveshare',now)
            self.assertEqual(self.chosen(now),'modem')
        self.assertEqual(self.chosen(37),'waveshare')
        self.s.update('waveshare','acquiring',None,37,37)
        self.assertEqual(self.chosen(37),'modem')
    def test_cached_replay_manual_and_off(self):
        self.put('modem',10)
        self.put('modem',25,10)
        self.assertIsNone(self.chosen(25))
        self.put('waveshare',25,100)
        self.assertIsNone(self.chosen(25))
        self.put('modem',26)
        for mode in ('waveshare','off'):
            self.s.settings['mode']=mode
            self.assertIsNone(self.chosen(26))
    def test_clock_stall_and_out_of_order(self):
        self.put('modem',10)
        self.put('modem',11)
        self.put('modem',12,10)
        self.assertEqual(self.s.snapshot(12,12)['fix']['time'], 11)
        self.s.update('modem', 'fix', g.position(11,50,30), 11, 40)
        self.assertIsNone(self.s.snapshot(11,40)['fix'])

    def test_client_snapshot_expiry(self):
        self.put('modem',10)
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'status.json'
            g.atomic_json(path,self.s.snapshot(10,10),0o640)
            self.assertEqual(g.read_status(path,11)['source'], 'modem')
            self.assertIsNone(g.read_status(path,21)['fix'])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)


if __name__ == '__main__':
    unittest.main()
