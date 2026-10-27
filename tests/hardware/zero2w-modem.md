# Mobile modem configuration checkpoint

2026-10-27. The Orange Pi was off; no modem was probed or configured on the board.
The owner identified the modem as **SIM7600G-H**, with a **Kyivstar** SIM. The
wiring description places the modem and a hub on USB1, with planned UPS power.
The specific carrier board, firmware/USB composition and SIM plan remain unknown.

## SIM7600G-H / Kyivstar bring-up target

The initial APN is `internet`, based on [Kyivstar's official settings](https://kyivstar.ua/no-war)
(checked 2026-10-27). This is a starting profile for ordinary mobile Internet;
a corporate/private APN, if assigned to this SIM, must be supplied separately.
No actual connection profile has been created on the board.

ModemManager has a [SimTech plugin with QMI support](https://github.com/linux-mobile-broadband/ModemManager/blob/main/src/plugins/simtech/mm-plugin-simtech.c).
A [SIM7600G-H integration example from Radxa](https://docs.radxa.com/en/rock5/rock5t/accessories/m2-b-key-sim7600g-h)
shows a QMI control port and network/serial interfaces. This supports starting
with the existing MM/NM backend; it does not prove the USB composition or kernel
support of this particular modem. Inspect `lsusb -t`, the loaded drivers and
`mmcli -L` on the Orange Pi before selecting its modem index. Do not copy another
board's GPIO power/reset sequence, force USB modes, or assume `ttyUSB2`/`wwan0`.

After that inspection, a profile can be prepared with:

```sh
# Replace MODEM with the discovered index. Saves only; does not connect.
armbian-config --api module_modem create MODEM kyivstar internet secondary home
```

Choose Internet routing explicitly for actual general Internet access. Start
with home-only; if national roaming is needed, explicitly select Allow roaming
according to the SIM plan. Check actual SIM lock and authentication requirements
locally. Leave radio bands and firmware defaults unchanged during first bring-up.

## Implementation

`module_modem` is separate from USB role and generic Netplan modules, under
Network → Mobile modem. It uses structured `mmcli -K` output for discovery and
status; NetworkManager owns GSM profiles and activation. The user selects a
modem index, but each created profile binds to its stable device identifier and
has a generated UUID. A profile marker limits subsequent actions to this module's
profiles; the marker is a management convention, not a security boundary.

[Menu/API help](../../tools/include/markdown/MDM001-footer.md) describes APN,
optional username, home/roaming, secondary/Internet routing, autoconnect,
inspection, editing, connection, disconnection and removal. No SIM/provider
values are guessed. Normal defaults are disconnected, no autoconnect, home-only,
no default route and no carrier DNS. Modem hardware, radio/SIM state and external
NetworkManager profiles can prevent activation even with a valid APN.

No packages/services, host network configuration or real profile was changed by
this implementation session. The module refuses inactive backend services rather
than migrating the system's network renderer. Native PIN/password prompts stay
on the terminal; debug tracing is disabled inside the module before raw modem
information is collected. Reports select non-secret fields rather than dumping
complete modem/SIM/profile objects.

## Local validation

78 Bats checks passed, including 19 modem cases. The suite uses fake service/MM/NM
responses for mutations and a real `nmcli --offline` profile-construction check
(nmcli 1.54.3 locally). An isolated PTY confirms the interactive path retains a
terminal and invokes `--ask`; it does not submit a PIN or authenticate a SIM.

Coverage includes multiple/no modems, private-field filtering, malformed input,
missing stable device identity, backend failure, explicit route/roaming defaults,
UUID ownership checks, active-profile edit/delete rejection, inactive updates,
autoconnect, bounded activation/disconnection, cancellation, and trace suppression.
The native offline check validates the generated NetworkManager properties with
no D-Bus writes. [Retained local log](evidence/2026-10-27/modem/local-tests.log).

## Hardware acceptance remaining

- Confirm SIM7600G-H revision/carrier board, USB mode and driver on this kernel.
- Check existing network renderer and MM/NM services before installing/enabling
  anything. Keep the current SSH route and USB1 modem/hub stable.
- Verify Kyivstar APN `internet` against this SIM plan; inspect lock/registration and roaming needs.
  Enter secrets locally; do not publish full modem logs or SIM identifiers.
- Create a device-bound profile, connect and verify IP, routes, DNS and real data
  transfer separately from radio registration or an NM "connected" state.
- Test disconnect/reconnect, unplug/replug, reboot and the chosen autoconnect
  policy, including locked SIM and absent network. Confirm other USB1 devices
  and Ethernet/Wi-Fi connectivity remain usable.
- Review radio mode/band selection, provider database lookup, supported HiLink
  configuration and failover after the actual USB composition and connection have been qualified.

Primary API references: [NetworkManager GSM settings](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nm-settings-nmcli.html),
[nmcli commands](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nmcli.html),
[ModemManager output keys](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli-output.c).
