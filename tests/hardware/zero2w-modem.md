# Mobile modem configuration checkpoint

2026-10-27. The Orange Pi was off; no modem was probed or configured on the board.
The modem model, SIM operator and APN have not yet been supplied. The earlier
wiring description places the modem and a hub on USB1, with planned UPS power.

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

- Identify model, USB mode and driver (QMI/MBIM/serial versus Ethernet/HiLink).
- Check existing network renderer and MM/NM services before installing/enabling
  anything. Keep the current SSH route and USB1 modem/hub stable.
- Supply the real operator APN; inspect SIM lock/registration and roaming needs.
  Enter secrets locally; do not publish full modem logs or SIM identifiers.
- Create a device-bound profile, connect and verify IP, routes, DNS and real data
  transfer separately from radio registration or an NM "connected" state.
- Test disconnect/reconnect, unplug/replug, reboot and the chosen autoconnect
  policy, including locked SIM and absent network. Confirm other USB1 devices
  and Ethernet/Wi-Fi connectivity remain usable.
- Review radio mode/band selection, provider database lookup, supported HiLink
  configuration and failover only after the modem model/use case is known.

Primary API references: [NetworkManager GSM settings](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nm-settings-nmcli.html),
[nmcli commands](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nmcli.html),
[ModemManager output keys](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli-output.c).
