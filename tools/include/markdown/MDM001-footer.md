### Mobile modem

Requires an existing, running **ModemManager + NetworkManager** stack. This module
does not install packages, start services, switch Netplan renderers or take over
networkd interfaces. The board's modem remains attached to USB1; USB0 role is an
independent setting.

- Status shows the model, SIM lock, registration, operator, signal quality and
  NetworkManager device state. It filters out modem/SIM identifiers and passwords.
- Create a profile with your operator's APN and optional username, then connect
  separately. Profiles bind to the selected modem's stable identity and are
  managed by UUID. Existing unrelated profiles are left alone.
- Choose **Secondary** to suppress the modem's default route and carrier DNS, or
  **Internet** to allow them with route metric 700. Existing routes, VPNs and DNS
  policies still affect actual traffic; this is not an automatic failover system.
- Home-only registration is the default. Allow roaming explicitly when your plan
  needs it, including national roaming. Mobile data can be chargeable.
- Automatic connection starts disabled. Enabling it may connect immediately.
  Editing a profile requires disconnection and disables autoconnect again.
- PIN and authentication passwords are requested by native `nmcli --ask` on an
  interactive terminal. They are not arguments to this module. Profiles use
  `not-saved` secret flags. A locked SIM may therefore require input after reboot;
  unattended operation depends on available secret agents and SIM state.

```sh
armbian-config --api module_modem status
armbian-config --api module_modem profiles
# Replace MODEM and your.apn with the index shown by Status and your provider APN:
armbian-config --api module_modem create MODEM mobile your.apn secondary home
# Use the UUID returned by create:
armbian-config --api module_modem show UUID
armbian-config --api module_modem connect-ask UUID
armbian-config --api module_modem disconnect UUID
armbian-config --api module_modem configure UUID your.apn internet roaming
armbian-config --api module_modem autoconnect UUID yes
armbian-config --api module_modem remove UUID
```

`connect UUID` is the noninteractive variant; it cannot ask for missing secrets.
`disconnect UUID` stops this connection, but other eligible profiles managed by
NetworkManager can still connect. `remove` only deletes an inactive profile owned
by this module. To undo a newly created profile, disconnect and remove its UUID.
Changes to an existing module profile use native NetworkManager updates; there is
no snapshot-based rollback of prior APN/settings. Inspect the profile before editing.

HiLink/router-style USB modems that expose Ethernet rather than a ModemManager
modem use Basic network setup and their vendor's administration interface.
This preview does not send arbitrary AT commands, switch USB composition, change
firmware, reset SIM PIN/PUK, select radio bands or configure SMS/voice.
