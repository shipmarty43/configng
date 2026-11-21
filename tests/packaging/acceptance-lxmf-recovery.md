# LXMF relay recovery and A733 header controls

The offline kit pairs the previous configng revision `59a145bd` with `13f6cad0` (packages `0.1~git1427.59a145bd` and `0.1~git1432.13f6cad0`). All three packages are versioned together. It includes pinned ARM64 runtime dependencies for Ubuntu Resolute. The Zero 3W header module is part of the configurator package. Its device-tree check used the separate Zero 3W Armbian 26.8.3 DT package. [A733 DTB and header checks](../../hardware/a733-io/README.md) · [Manual and schematic audit](../hardware/pin-manual-audit.md).

## Workstation tests, 2026-11-21

Three memory-backed SX1262 nodes used RNS 1.6.1 and LXMF 1.3.1, independent processes, one RNode pseudo-terminal per node, temporary identities and per-node SQLite databases. A and C could reach only B. Fault tests accelerated announce scheduling, stamp work and keepalives. [Test and reproduction](../../hardware/reticulum-sx1262/README.md#relay-and-mailbox-recovery).

| Test | Observed behavior |
|---|---|
| Drop a second RNode fragment | A showed `sending`, C's inbox was empty. B was killed and returned with the same transport identity. A and C again reported two hops through B and exchanged a new message with a verified delivery proof. |
| Drop the proof after receipt | C had the signed letter. A lacked confirmation. Replaying the same signed envelope left one inbox row. Restarting A recovered its original delivery address and set the interrupted outbox item to `unconfirmed`. |
| Collect while sender is unaware of collection | With C offline, B accepted a letter and indexed it. After B was killed and restarted, C collected and verified message ID `ac9c056d581664f3a298e051ad0916b428d547dc34ebbb677354405b0e3e843f`. Two completed collections left one copy. A retained `accepted-by-node`. |
| Contact route | Both mailbox instances reported two hops on RNodeInterface via `5995880026316670c72ad1d24d43c428` and a delivery announce observed for the selected contact. The menu tests also exercised contact selection for routing and propagated sends. |

## ARM64 installation and persistence

The staged lifecycle test on the clean Zero 2W Armbian Resolute image installed `59a145bd`, upgraded to the intermediate `45e6eede`, downgraded and checked the previous packages after a cold guest reboot. The combined snapshot of the LXMF identity and delivery address, contact and message tables, Meshtastic node and message tables, Reticulum configuration and 500,000 Hz SPI request retained SHA-256 `ee274d0da0c078c174318a83d2de7ad326f7c3ee0c6eb9b833bd891a0248aa59`. The guest opened the installed MESH01 and SXMD01 menus. The kernel device namespace contained no physical SPI or GPIO device, and the VM had only loopback.

Reproduce the final package and fault checks with the [mesh-recovery VM scenario](../../packaging/zero2w/README.md#lxmf-relay-and-propagation-acceptance).

A second run started with another clean copy-on-write layer, installed the previous packages, seeded new test identities and messages, then upgraded to `13f6cad0`. The guest verified the expected current package versions and the unchanged snapshot `35349909940a8feeb0e8bb892eb53ba1c63e6926a88f20e6c8a8023934fcfd27`. Both installed menus rendered. On the initial fault-test attempt the emulated relay's first serial handshake timed out under load after its restart. RNS also logged path-request stamp worker timeouts. The harness now waits for the upstream reconnect and validates all radio parameters, and selects lower path-request stamp work only for the fault fixture. The replay uses a child disk of the powered-off upgraded guest and checks its installed version and complete saved snapshot before testing.

In the packaged ARM64 replay, A and C found two hops via B (`2865b60444de04b63a40155f603dd229`). The interrupted transfer was unconfirmed, a new signed reply was delivered, and dropping a subsequent return proof left one verified copy at the recipient. The upstream RNode connection recovered after a transient startup mismatch. B reindexed one stored letter after restarting. C collected message `fd00f08beb4c6520ccc5d3c916aff94a613c00ae0557a3c573bc55fc4698d790` with a verified signature. Both collection requests completed; the sender retained `accepted-by-node`.

The replay completed `PASS-PACKAGED-LXMF-RECOVERY`, downgraded all three packages to `59a145bd` and powered down. A new cold guest boot verified the previous versions and the same full state digest `35349909940a8feeb0e8bb892eb53ba1c63e6926a88f20e6c8a8023934fcfd27`, including the 500,000 Hz SPI selection. Both phases exited successfully. The guest had one emulated Cortex-A53 CPU, 640 MiB RAM, loopback networking only and no SPI or GPIO devices. Physical Zero 3W boot, electrical signals and on-air packet exchange were outside this run.

The local offline archive is `zero2w-lxmf-recovery-arm64.tar`, SHA-256 `b2f9028e9db228f9a2944d5e3e3fa450835e474553889a9531a5450e6264d4c1`.
