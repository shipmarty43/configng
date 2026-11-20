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
| LXMF mailbox | Opens the inbox, outbox, contact picker and composer. The background receiver keeps accepting messages after the menu closes. |

```sh
sudo armbian-config-zero2w --cmd MESH01
sudo armbian-config-zero2w --api module_mesh_local meshtastic inspect
sudo armbian-config-zero2w --api module_mesh_local reticulum inspect
```

## LXMF mailbox

Open **System → Hardware → Mesh services → LXMF mailbox**. The direct entry
to Mesh services on the board is `sudo armbian-config-zero2w --cmd MESH01`.

- **My LXMF delivery address** displays the mailbox's persistent 32-digit address.
- **Add or rename a contact** saves a name and LXMF delivery address. Saving
  the same address again updates its label.
- **Read incoming messages** lists newest arrivals first. Open a row to read
  the message text, subject, sender address and signature status. Unknown or
  invalid signatures are labelled `unverified`. The contact name is a local label.
- **Send to a saved contact** shows each name and full address. Choose one,
  enter an optional subject and a message, and press OK to queue it. Cancelling
  the contact picker or composer leaves the outbox alone.
- **Sent messages and delivery status** shows `queued` while waiting for a
  known route, `sending` after handing the message to LXMF, and `delivered`
  after LXMF confirms delivery. Route discovery expires after ten minutes.
  An interrupted send with an unknown outcome is marked `unconfirmed`;
  sending it again requires another explicit user action.

The optional systemd service uses the board's shared Reticulum instance.
Install the fork containing the mailbox menu and run from its checkout:

```sh
sudo /opt/opi-mesh/venv/bin/pip install --only-binary=:all: 'lxmf==1.3.1' 'rns==1.6.1'
sudo install -m644 hardware/mesh/lxmf_mailbox.py /opt/opi-mesh/
sudo install -m644 hardware/mesh/opi-lxmf.service /usr/local/lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opi-lxmf.service
```

The service starts with `opi-reticulum`. It creates an independent mailbox
under `/var/lib/opi-lxmf/` on first use. The private identity, contacts, inbox
and outbox survive restarts. Message bodies are stored locally in SQLite.
Earlier acceptance fixtures retain their own identities and inbox files.
For future LAN use, configure the desired Reticulum TCP interface as described below.

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
sudo /opt/opi-mesh/venv/bin/pip install 'meshtastic==2.7.11' 'rns==1.6.1' 'lxmf==1.3.1'
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
LAN address and restart the Reticulum service. The default profile uses loopback.
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

### Two physical hosts over LAN

Use a workstation running Python 3.14 and RNS 1.6.1, and the installed
`opi-reticulum` on the board. During the acceptance run the daemon kept its
loopback listener and temporarily added a TCP server on its Ethernet address.
The systemd address filter allowed localhost and the workstation address.
To repeat with the LAN profile above, restrict access to the intended peer
while the listener is active.

On the workstation, set `BOARD_IP` to the board's Ethernet address and
`RNS_PYTHON` to the absolute path to the interpreter in the RNS environment.
Run from the fork checkout:

```sh
systemd-run --user --quiet --wait --pipe -p MemoryHigh=160M -p MemoryMax=256M \
    -p MemorySwapMax=0 -p CPUQuota=150% -p TasksMax=64 -p RuntimeMaxSec=565 \
    --setenv=PYTHON_CPU_COUNT=2 "$RNS_PYTHON" \
    "$PWD/hardware/mesh/check_reticulum_lan.py" workstation "$BOARD_IP"
```

Use the printed destination hash for `DESTINATION` on the board. The board
role attaches to the running daemon and requests a path, so it can start
after the workstation's first announcement. Neither host needs serial access.

```sh
sudo systemd-run --quiet --wait --pipe -p DynamicUser=yes -p User=opi-reticulum \
    -p StateDirectory=opi-reticulum -p StateDirectoryMode=0700 -p PrivateDevices=yes \
    -p PrivateTmp=yes -p MemoryHigh=160M -p MemoryMax=256M -p CPUQuota=100% \
    -p TasksMax=64 -p RuntimeMaxSec=550 --setenv=PYTHON_CPU_COUNT=1 \
    /opt/opi-mesh/venv/bin/python /opt/opi-mesh/check_reticulum_lan.py board "$DESTINATION"
```

On 2026-11-20, both kernels showed the direct TCP connection from the
workstation to port 4242 of the board's Ethernet address. Over an established
Reticulum link the board sent independent 32-byte and 768-byte random
challenges. It compared both replies byte for byte, and the workstation
observed both requests and link closure. Systemd reported peak memory of
35.5 MiB for the workstation test and 28.2 MiB for the board test process.
After restoring the profile, the runtime and persistent config matched the
original files and the only listener on port 4242 was `127.0.0.1`.

### Signed LXMF messages over LAN

Two independent LXMF clients exchanged UTF-8 messages through the board's
Reticulum TCP service. The workstation sent a message in Cyrillic and the
board replied after verifying it. Each receiver checked the expected contact,
destination, title, body, encrypted direct delivery and signature. It then
saved the incoming message in its private `inbox/` and reopened it with the
upstream library. Each sender required the LXMF `DELIVERED` callback.
[Upstream LXMF](https://github.com/markqvist/LXMF)

Use the two-host LAN profile above. Install `lxmf==1.3.1` alongside
`rns==1.6.1` in both Python environments. Install
`check_lxmf_lan.py` under `/opt/opi-mesh/` on the board. These Bash helpers
set the resource bounds used in the test. On the **workstation**, run from
the fork checkout using the absolute path to its LXMF Python interpreter:

```sh
PC_STATE=$(mktemp -d)/contact
pc_lxmf() {
    systemd-run --user --quiet --wait --pipe -p MemoryHigh=160M -p MemoryMax=256M \
        -p MemorySwapMax=0 -p CPUQuota=150% -p TasksMax=64 -p RuntimeMaxSec=1120 \
        --setenv=PYTHON_CPU_COUNT=2 "$RNS_PYTHON" -u "$PWD/hardware/mesh/check_lxmf_lan.py" "$@"
}
pc_lxmf init "$PC_STATE"
```

On the **board**, prepare a separate identity in a new directory owned by
the Reticulum service:

```sh
BOARD_STATE=/var/lib/opi-reticulum/lxmf-test
board_lxmf() {
    sudo systemd-run --quiet --wait --pipe -p DynamicUser=yes -p User=opi-reticulum \
        -p StateDirectory=opi-reticulum -p StateDirectoryMode=0700 -p PrivateDevices=yes \
        -p PrivateTmp=yes -p MemoryHigh=160M -p MemoryMax=256M -p CPUQuota=150% \
        -p TasksMax=64 -p RuntimeMaxSec=1120 --setenv=PYTHON_CPU_COUNT=2 \
        /opt/opi-mesh/venv/bin/python -u /opt/opi-mesh/check_lxmf_lan.py "$@"
}
board_lxmf init "$BOARD_STATE"
```

Exchange the printed **public destination hashes** and choose the same fresh
`RUN_ID` on both hosts. Start the board command first, then start the workstation
command in its own terminal:

```sh
# Orange Pi
board_lxmf board "$BOARD_STATE" "$PC_DEST" "$RUN_ID"
# Workstation
pc_lxmf workstation "$PC_STATE" "$BOARD_DEST" "$RUN_ID" "$BOARD_IP"
```

**2026-11-20 result.** Both directions passed, then passed again after
restarting both clients with the original identities and a new run label.
All four sender message IDs matched the verified receiver IDs. Each inbox
contained two distinct mode-0600 files. The first run peaked at 37.4 MiB on
the workstation and 35.9 MiB on the board for the respective test clients.
After the test the board again listened only on `127.0.0.1:4242`.

### Mailbox acceptance through the configurator

On 2026-11-20 a workstation connected directly to the Zero 2W test LAN
listener. The operator path was exercised in the actual installed terminal UI:

1. Open `MESH01`, choose **LXMF mailbox → Add or rename a contact**, and save
   the workstation's address. Give the address under **My LXMF delivery address**
   to the workstation client.
2. Run the workstation half of `check_lxmf_lan.py` with that mailbox as its
   peer and a fresh run label. It sends the initial signed message.
3. In **Read incoming messages**, open the new row. The sender label, full
   address, `verified` signature status and Cyrillic text were visible.
4. Choose **Send to a saved contact**, select the workstation, and submit
   the subject `LXMF board` and body `Плата приняла сообщение. [RUN_ID]`,
   replacing `RUN_ID` with the workstation's run label.
5. Open **Sent messages and delivery status**. The selected message reached
   `delivered`. The workstation independently verified its signature and
   exact title/body and reopened its saved copy.

The exchange passed twice, including a mailbox-service restart. Both incoming
IDs matched the workstation's delivery confirmations and both outgoing IDs
matched the verified messages at the workstation. The contact, mailbox address
and history were retained. The temporary LAN listener was then removed.

## Zero 2W board results, 2026-11-20

| Check | Result |
|---|---|
| Meshtastic phone API | Client 2.7.11 read the simulator's node ID and firmware 2.7.26. |
| Meshtastic text | Two native ARM64 firmware processes exchanged distinct messages over isolated loopback in both directions. |
| Reticulum 1.6.1 | Independent TCP peer discovered a temporary destination, delivered 24 exact bytes through the shared daemon and received its delivery proof. |
| Configurator | Production module assembly and five Bats checks passed. Both native clients returned node or interface information through the installed configurator API. |
| Service lifecycle | Both choices appeared in the installed text menu. Each stopped cleanly, inspection of the stopped unit returned an error, and inspection succeeded again after starting it. Boot enablement stayed off. |
| Device and network isolation | Both service device trees excluded SPI, GPIO and the GNSS UART. The simulator had only loopback in its network namespace. On the host, only `127.0.0.1:4242` listened on the two tested ports. `gpsd` and `opi-gnss` remained active. |

Physical Meshtastic peer tests and Reticulum over a radio adapter remain
separate milestones. The test profile
has no GNSS or MQTT integration.
