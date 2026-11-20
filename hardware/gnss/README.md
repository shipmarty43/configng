# Zero 2W GNSS sources

The **GNSS receivers** item in System → Hardware selects the local position used by
application clients. Waveshare is the L76K on the shield UART (physical 8/10).
SIM7600G-H is a separate USB receiver. Selecting a position leaves the SX1262
radio available to its current owner.

## Install on Armbian

Install the optional component from the fork checkout. The default mode is Off.

```sh
sudo install -Dm755 hardware/gnss/opi_gnss.py /usr/local/bin/opi-gnss
sudo install -Dm644 hardware/gnss/opi-gnss.service /usr/local/lib/systemd/system/opi-gnss.service
sudo systemctl daemon-reload
```

Configure the board's UART for the L76K and give its verified path to gpsd at
9600 baud. Check the active kernel console and serial getty before assigning
the UART. In **GNSS receivers → Waveshare UART** enter the exact device path
that gpsd reports. The provider reads TPV on localhost port 2947. gpsd owns the
serial descriptor. A missing path is reported as disabled. [gpsd TPV protocol](https://gpsd.gitlab.io/gpsd/gpsd_json.html)

For the modem, the provider discovers the model through ModemManager on each poll.
It checks GPS-NMEA capability and the current enabled sources before reading
location. A disabled GPS engine is reported in status. To use it, explicitly
enable GPS-NMEA on the intended modem with `mmcli -m ID --location-enable-gps-nmea`
after inspecting `mmcli -m ID --location-status`. Selection itself makes
read-only requests. More than one matching SIM7600 is reported as ambiguous.
[ModemManager Location](https://www.freedesktop.org/software/ModemManager/api/latest/gdbus-org.freedesktop.ModemManager1.Modem.Location.html)

## Select and read

Use the configurator menu or `armbian-config --api module_gnss` with one
of `auto`, `waveshare`, `modem`, `off`, `prefer modem`, `prefer waveshare`,
`device /dev/UART` or `status`. Mode and preference persist in
`/etc/opi-gnss.json`. Selecting a receiver enables the local provider at boot.
Off stops it and removes its boot enablement. Each underlying navigation
receiver retains its original system configuration.

`opi-gnss status` emits JSON with source, fix, receiver health and age. The
snapshot lives in `/run/opi-gnss/status.json`, readable by root and the dialout
group. Clients can invoke the status command for an expiry check at read time.
Coordinates are degrees. Timestamps are Unix UTC seconds. GPSD dimension and
horizontal error estimates are included when supplied. An unavailable fix is
JSON null. A synchronized host clock is needed to compare receiver timestamps.

Auto initially prefers Waveshare. A fix expires after 10 seconds. Repeated
samples with the same UTC timestamp cannot extend its lifetime. A manual
selection waits for its specific receiver. Auto immediately falls back to a fresh
alternative, then waits for 15 seconds of continuous preferred-source coverage
before returning. The default one-second tolerance for a future timestamp allows
small clock differences. No location is sent to the network by this service.

## Reproduce offline

```sh
cd hardware/gnss
python3 -m unittest -v test_gnss
python3 check_gpsd_pty.py /usr/sbin/gpsd
dbus-run-session -- /usr/bin/python3 check_modem_bus.py
```

The last test requires mmcli, python3-dbus and python3-gi. It registers the
fixture on its own session bus. The UART test starts a local gpsd with a PTY
and sends generated RMC/GGA data. Board acceptance includes identifying the UART,
cold fixes outdoors from both receivers, failover during USB disconnect,
restoration after reconnect and continued modem data service.
