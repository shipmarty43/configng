"""Run with dbus-run-session -- /usr/bin/python3 check_modem_bus.py."""
from datetime import datetime, timezone
import json
import os
import subprocess
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

import opi_gnss as gnss
from test_gnss import sentence

MANAGER = 'org.freedesktop.ModemManager1'
BASE = '/org/freedesktop/ModemManager1'
MODEM = MANAGER + '.Modem'
LOCATION = MODEM + '.Location'
PATH = BASE + '/Modem/17'
PROP = 'org.freedesktop.DBus.Properties'
OM = 'org.freedesktop.DBus.ObjectManager'


def properties():
    return {MODEM: {'Model': 'SIMCOM_SIM7600G-H', 'PrimaryPort':'wwan-test',
                    'DeviceIdentifier':'fixture', 'State': dbus.Int32(8),
                    'Manufacturer':'SIMCom', 'Device':'/sys/devices/test', 'Drivers':dbus.Array(['option'],signature='s'),
                    'Ports':dbus.Array([('wwan-test',dbus.UInt32(3))],signature='(su)'),
                    'CurrentModes':dbus.Struct((dbus.UInt32(8),dbus.UInt32(0))),
                    'SignalQuality':dbus.Struct((dbus.UInt32(0),dbus.Boolean(False))),
                    'UnlockRetries':dbus.Dictionary({},signature='uu'),
                    'Sim':dbus.ObjectPath('/'), 'SimSlots':dbus.Array([],signature='o'),
                    'SupportedModes':dbus.Array([(dbus.UInt32(8),dbus.UInt32(0))],signature='(uu)'),
                    'CurrentBands':dbus.Array([0],signature='u'), 'SupportedBands':dbus.Array([0],signature='u')},
            LOCATION: {'Capabilities': dbus.UInt32(4), 'Enabled':dbus.UInt32(4),
                       'SignalsLocation':dbus.Boolean(False)}}


class Manager(dbus.service.Object):
    @dbus.service.method(OM, in_signature='', out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        return {PATH:properties()}


class Modem(dbus.service.Object):
    @dbus.service.method(PROP, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return properties().get(interface, {})

    @dbus.service.method(LOCATION, in_signature='', out_signature='a{uv}')
    def GetLocation(self):
        now = datetime.now(timezone.utc)
        data = sentence(f'GNRMC,{now:%H%M%S},A,5027.000,N,03030.000,E,0,0,{now:%d%m%y},,,A')
        return {dbus.UInt32(4):dbus.String(data)}


if __name__ == '__main__':
    if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        sys.exit('Requires an isolated dbus-run-session')
    if sys.argv[1:]==['fixture']:
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        name = dbus.service.BusName(MANAGER,bus,do_not_queue=True)
        manager, modem = Manager(name,BASE), Modem(name,PATH)
        print('ready', flush=True)
        GLib.MainLoop().run()
    else:
        # Both the fixture and the actual mmcli process use only this session bus.
        def call(*args):
            return json.loads(subprocess.check_output(['mmcli','--test-session','-J',*args],timeout=4))
        with subprocess.Popen([sys.executable,__file__,'fixture'], stdout=subprocess.PIPE) as fixture:
            try:
                assert fixture.stdout.readline()==b'ready\n'
                state, fix = gnss.poll_modem(call)
                assert state=='fix' and fix['lat']==50.45 and fix['lon']==30.5
                print('PASS: private ModemManager D-Bus fixture -> real mmcli JSON -> SIM7600 fix')
            finally:
                fixture.terminate()
