# Zero 2W package acceptance on Armbian Resolute

Tested on 21 November 2026. The input was the published desktop image
`Armbian_community_26.11.0-trunk.108_Orangepizero2w_resolute_current_6.18.57_xfce_desktop.img`.
The raw file and the streamed expansion of the checked XZ archive had the
same SHA-256, `a398fa766ee849ef30f367534aa09d640ea0ff9d11f139a5bf2838e4a17b26fe`.
The compressed archive matched its companion checksum,
`5aa115e02d367b4a6865832463a6b230c42b3773fe53acbba27b6d93fece0711`.

QEMU booted the image's `6.18.57-current-sunxi64` kernel and systemd root
on an emulated Cortex-A53 with 640 MiB of guest RAM. The guest reported
`arm64` to dpkg and only `lo` as a network interface. A read-only virtual
disk supplied the packages. The DT supplied a disabled SPI endpoint with
a 2 MHz clock ceiling. The test measures persistence of the selected clock.
The physical bus and RF hardware were outside this test.

| Release | Package version | Configurator source |
|---|---|---|
| Previous | `0.1~git1410.7a48de26` | RNode adapter and SPI clock controls |
| Current | `0.1~git1411.9dbb3855` | RNode packet diagnostics and patched RNS signal decoding |

Both releases contain `armbian-config-zero2w`, `opi-zero2w-mesh` and
`opi-zero2w-mesh-runtime`. A second build from the same inputs reproduced
all six archive files byte for byte. The executable and the twelve bundled
native Python extensions in each runtime have the AArch64 ELF machine type.

The LXMF service generated its own identity and address. The Meshtastic
mailbox reported firmware 2.7.26 from the isolated software simulator.
With the workers stopped, the fixture used the installed storage APIs to
save an incoming and a queued outgoing UTF-8 message for each protocol,
a named LXMF contact and a Meshtastic node. The configurator set the bus
clock to 500,000 Hz. A local edit to the Reticulum conffile served as an
additional preservation check.

The comparison includes the message IDs, complete bodies, peers, directions,
timestamps and statuses, contact and node identifiers, and hashes of the LXMF
identity, delivery address, SPI setting and Reticulum conffile. Both SQLite
databases must return `ok` from `PRAGMA integrity_check`. The aggregate is
specific to this run because LXMF generates a new identity on each clean
install.

| Stage | Result |
|---|---|
| Direct installation of the current release on a second clean overlay | APT installed the current packages. Diagnostics reported a free ownership lock, mode `off` and the 2 MHz DT default. Software and radio services were inactive. |
| Fresh installation of the previous release | APT installed three project packages and nine local Ubuntu dependencies. Both runtimes imported. The simulator and TCP services started only when requested. |
| Upgrade | APT upgraded exactly the three project packages. The new RNS decoder hash matched. The SPI diagnostics displayed 500,000 Hz. The packaged MESH01 and SXMD01 terminal dialogs rendered. |
| Downgrade | APT downgraded exactly the three project packages. The previous decoder hash returned, and both files introduced for diagnostics were removed. |
| Boot after downgrade | The boot ID changed, dpkg reported the previous version of all three packages, and the configurator read back 500,000 Hz. |

The same state digest, `1545dcafa39dd30f67dee663ddb4ed52dbf41479562f185ebff13f5fba2b3b74`,
was observed at baseline, after upgrade, after downgrade and after reboot.
At every stage `dpkg --audit` was empty and the SHA-256 of the stock
`/usr/bin/armbian-config` matched the pristine guest copy. The two radio
services stayed inactive.

During configurator startup in a guest with no default route, iproute2
printed a warning about an incomplete command. The shared environment
initializer queries the default adapter before it falls back to loopback.
The SPI commands and both terminal menus completed successfully.

The host cgroup limited each guest run to 1,000 MiB, with swap disabled.
Guests ran one at a time. Recorded memory peaks were 820.2 MiB for the
upgrade cycle and 754.7 MiB for the independent current install. Both
cgroups recorded zero OOM kills. The writable layers occupied 271 MiB and
167 MiB respectively, as reported by `du -h`. The raw base image retained
its original SHA-256 after the tests.

The locally delivered offline archive was 10,833,920 bytes, SHA-256
`be24c8c6a439a92b80a48a3a0560e05b97e8b733254bedd963bc084c0cfc67f3`.
It contains the six project archives, nine Ubuntu dependencies, their
checksums, the installer and usage instructions.
