# Meshtastic simulator and Reticulum TCP on Armbian

**System → Hardware → Mesh services** controls two independent systemd services.
The Meshtastic node runs the official native firmware in simulation mode.
Reticulum runs the upstream `rnsd` and accepts local TCP peers at
`127.0.0.1:4242`. Both use private device trees and separate state directories.
GNSS selection and the LoRaWAN radio service have separate lifecycles.

| Configurator action | Effect |
|---|---|
| Start / Stop | Changes the selected service for the current boot. State survives a stop and start. |
| Inspect Meshtastic | Connects the official Python client to the simulator's phone API on port 4403 in its private network namespace. Prints node ID and firmware version. |
| Inspect Reticulum | Runs `rnstatus` against the named shared instance using the daemon's account and state directory. Reports interface, peer and traffic statistics. |

```sh
sudo armbian-config-zero2w --cmd MESH01
sudo armbian-config-zero2w --api module_mesh_local meshtastic inspect
sudo armbian-config-zero2w --api module_mesh_local reticulum inspect
```

## Install on an ARM64 Zero 2W running Ubuntu 26.04

The board used the ARM64 package from the [Meshtastic beta PPA](https://meshtastic.org/docs/meshtasticd/installation/ubuntu/),
the upstream Meshtastic Python client, and Mark Qvist's [Reticulum package](https://pypi.org/project/rns/1.6.1/).
The following commands run from the fork checkout. Only the native executable is needed from the PPA package.

```sh
stage=$(mktemp -d)
pkg=meshtasticd_2.7.26.61~ppa54e0d8d~resolute_arm64.deb
curl -fL "https://ppa.launchpadcontent.net/meshtastic/beta/ubuntu/pool/main/m/meshtasticd/$pkg" -o "$stage/$pkg"
(cd "$stage" && echo "6180a7be3b12eae3abb75a532c00333cf2254e4704c41c401cee5b555f55843d  $pkg" | sha256sum -c -) &&
    dpkg-deb -x "$stage/$pkg" "$stage/native"
sudo apt-get --no-install-recommends satisfy "$(dpkg-deb -f "$stage/$pkg" Depends)"
sudo apt-get --no-install-recommends install python3-venv python3-cryptography
sudo install -Dm755 "$stage/native/usr/bin/meshtasticd" /opt/opi-mesh/meshtasticd
sudo python3 -m venv --system-site-packages /opt/opi-mesh/venv
sudo /opt/opi-mesh/venv/bin/pip install 'meshtastic==2.7.11' 'rns==1.6.1'
sudo install -m644 hardware/mesh/*.py /opt/opi-mesh/
sudo install -d /etc/opi-mesh /usr/local/lib/systemd/system
# Preserve any existing site-specific TCP configuration on upgrade.
if ! sudo test -e /etc/opi-mesh/reticulum.conf; then
    sudo install -m644 hardware/mesh/reticulum.conf /etc/opi-mesh/reticulum.conf
fi
sudo install -m644 hardware/mesh/*.service /usr/local/lib/systemd/system/
sudo systemctl daemon-reload
```

Use an assembled version of this fork containing `MESH01`. Start either node
from the menu. The simulator uses a fixed test node ID and private
`/var/lib/opi-meshtastic-sim` storage. Reticulum keeps its identity and state
in `/var/lib/opi-reticulum`. Its service reads `/etc/opi-mesh/reticulum.conf`
on every start. To accept LAN peers, set `listen_ip` to the board's intended
LAN address and restart the Reticulum service. The tested profile uses loopback.
[Reticulum TCP interface configuration](https://reticulum.network/manual/interfaces)

## Reproduce the board checks

The Meshtastic check starts two additional temporary firmware instances with
different node IDs. The private namespace contains just loopback. A multicast
route inside it carries simulated packets. The test checks the sender ID and
exact text received by the other official Python client in both directions.

```sh
sudo systemd-run --quiet --collect --wait --pipe -p PrivateDevices=yes \
    -p PrivateNetwork=yes -p PrivateTmp=yes -p RuntimeMaxSec=100 \
    /bin/sh -ec 'ip link set lo multicast on; ip route add 224.0.0.69/32 dev lo src 127.0.0.1; exec /opt/opi-mesh/venv/bin/python /opt/opi-mesh/check_meshtastic_sim.py'
```

For Reticulum, start the TCP node with the supplied loopback config and no
other peers connected. The test attaches a temporary destination to the real
service and starts a second RNS instance with its own identity, config and
TCP client. It checks both the random application payload at the destination
and the delivery proof at the sender. The first announcement for a new
destination can take several minutes to stamp on the H618.

```sh
sudo systemctl start opi-reticulum
sudo systemd-run --quiet --collect --wait --pipe -p DynamicUser=yes \
    -p User=opi-reticulum -p StateDirectory=opi-reticulum -p StateDirectoryMode=0700 \
    -p PrivateDevices=yes -p PrivateTmp=yes -p RuntimeMaxSec=605 \
    /opt/opi-mesh/venv/bin/python /opt/opi-mesh/check_reticulum_tcp.py
```

## Zero 2W board results, 2026-11-20

| Check | Result |
|---|---|
| Meshtastic phone API | Client 2.7.11 read the simulator's node ID and firmware 2.7.26. |
| Meshtastic text | Two native ARM64 firmware processes exchanged distinct messages over isolated loopback in both directions. |
| Reticulum 1.6.1 | Independent TCP peer discovered a temporary destination, delivered 24 exact bytes through the shared daemon and received its delivery proof. |
| Configurator | Production module assembly and five Bats checks passed. Both native clients returned node or interface information through the installed configurator API. |
| Service lifecycle | Both choices appeared in the installed text menu. Each stopped cleanly, inspection of the stopped unit returned an error, and inspection succeeded again after starting it. Boot enablement stayed off. |
| Device and network isolation | Both service device trees excluded SPI, GPIO and the GNSS UART. The simulator had only loopback in its network namespace. On the host, only `127.0.0.1:4242` listened on the two tested ports. `gpsd` and `opi-gnss` remained active. |

External LAN peers, LXMF, a physical Meshtastic peer and Reticulum over a
radio adapter remain separate milestones. The test profile has no GNSS or
MQTT integration.
