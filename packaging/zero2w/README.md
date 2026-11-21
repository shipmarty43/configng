# Offline packages for Orange Pi Zero 2W

This kit targets Armbian on Ubuntu Resolute, ARM64, with Python 3.14.
`armbian-config-zero2w` installs the fork alongside the distribution's
`armbian-config`. The other two packages install the mesh services and their
matching runtime. All three versions change together. Maintainer scripts
reload systemd's unit files without enabling a radio, a simulator or a
mailbox. The default SX1262 profile is `no-radio`.

## Use a prepared kit

Extract the tar archive and run one command from its directory:

```sh
sudo ./apply.sh current     # install or upgrade
sudo ./apply.sh previous    # install the previous release or downgrade to it
```

The script verifies SHA-256 sums and installs local files with APT. The kit
includes the nine Ubuntu packages missing from the tested image. APT checks
dependencies against the installed system. A different base image may need
other libraries. Existing Ubuntu packages are left to the distribution.
Neither command changes `/boot` or starts a radio profile.

Use `sudo armbian-config-zero2w --cmd MESH01` to open the mesh menu.
`sudo armbian-config-zero2w --cmd SXMD01` opens the SX1262 menu. `sudo armbian-config-zero2w --cmd SPI001` opens the per-device SPI0/SPI1 boot clock settings. I2C001, UART01 and PWM001 open the [I²C bus, UART and header PWM controls](../../hardware/h616-io/README.md).
LXMF and Meshtastic keep their databases in `/var/lib/opi-lxmf/` and
`/var/lib/opi-meshtastic-mail/`. LXMF keeps its local identity in its state
directory. The selected bus clock lives in
`/etc/armbian-config/sx1262-spi-hz`. The packages own none of these files.
The editable `/etc/opi-mesh/reticulum.conf` is a dpkg conffile.

## Rebuild both releases

Run from the repository root with a full Git history, Python 3.12+ with
pip, Bash, jq, GNU patch and dpkg-deb. Choose a disk-backed work directory.
Only the fetch step needs Internet access.

```sh
mkdir -p work release/previous release/current
python3 packaging/zero2w/fetch.py work/inputs
python3 packaging/zero2w/build.py 2fe98dfc --inputs work/inputs --work work --output release/previous
python3 packaging/zero2w/build.py HEAD --inputs work/inputs --work work --output release/current
mkdir -p release/ubuntu
install -m644 work/inputs/ubuntu/*.deb release/ubuntu/
cp packaging/zero2w/{apply.sh,README.md} release/
(cd release && sha256sum previous/*.deb current/*.deb ubuntu/*.deb > SHA256SUMS)
tar -cf zero2w-resolute-offline.tar release/
```

These commands use the previous UART boot-profile release for downgrade testing. The original release pair and results are recorded in the [acceptance report](../../tests/packaging/acceptance-resolute.md).

The revision selects the fork sources, assembled menus, units and applicable
RNode fixes. The manifest pins the native ARM64 meshtasticd, wheels and
Ubuntu dependencies. The build verifies the inputs and uses one compression
thread. Files are staged on disk and compressed one package at a time.

## Reproduce the acceptance test

On a Linux host with QEMU system emulation for AArch64, qemu-img, dtc,
fdtoverlay, sfdisk, debugfs, mke2fs, cpio and a static ARM64 BusyBox:

```sh
tests/packaging/run-armbian-vm.sh /path/to/clean.img release /path/to/arm64/busybox work/lifecycle
tests/packaging/run-armbian-vm.sh /path/to/clean.img release /path/to/arm64/busybox work/fresh fresh-current
```

Use the uncompressed regular image file. The harness extracts its own kernel
and starts the original root filesystem via a new qcow2 overlay. QEMU has
one vCPU and 640 MiB of guest RAM. It exposes a private serial console and
two virtual storage devices. The guest has only loopback. A disabled DT node
supplies the SPI clock ceiling. No SPI transfer, physical device or SD card
is involved. The mesh tests start only the software services. They seed the
mailbox storage through the installed Python modules, stop its workers before
queuing outgoing messages, and check the complete saved message rows.

The first boot installs the older packages, upgrades, opens the menus and
downgrades. A second boot checks the old versions and data again. Both boots
must exit successfully. Logs and the writable overlay stay in the chosen
work directory for inspection. The overlay contains a generated test identity.

The independent `fresh-current` run installs the current release directly on a second clean overlay and checks the default SPI clock and idle owner.
