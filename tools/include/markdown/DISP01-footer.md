### Displays

**System → Desktop → Displays** separates hardware discovery from desktop settings.
The status view reads DRM connector status, enabled state and advertised modes.
Advertised modes are not the active resolution; neither a connector nor an
installed driver proves that a physical display works.

Choose a local graphical session to open its native settings panel. Resolution,
refresh rate, layout, rotation and scaling are provided where supported by that
desktop and driver. GNOME, Plasma, XFCE, Cinnamon, MATE and LXQt have panel
mappings; no packages are installed automatically. Confirm/revert behaviour and
persistence remain those of the native panel.

The panel is started through the selected user's systemd manager, not as root.
It uses that manager's graphical environment and fixed executable arguments.
Remote, root, greeter and non-graphical sessions are rejected. Ambiguous active
sessions, unknown desktops, missing panels or missing user-manager environments
produce an explanation instead of guessing a display or editing Xauthority.
Some desktops do not publish their name/environment to logind/systemd; open
their settings directly from the desktop in that case. SSH can launch a panel
only when a suitable local graphical session already exists.

```sh
armbian-config --api module_screen_settings status
armbian-config --api module_screen_settings sessions
armbian-config --api module_screen_settings open SESSION_ID
```

This does not configure boot-console resolution or implement a Wayland-wide
mode-setting protocol. It does not enable GPU/TV-out overlays. H618 CVBS needs
the kernel display pipeline, TV encoder, DAC and board wiring to work first;
see `tests/hardware/zero2w-cvbs.md` in the source tree.

Implementation reference: [systemd-run](https://www.freedesktop.org/software/systemd/man/252/systemd-run.html).
Validation uses temporary DRM fixtures and mocked session/package services.
Live desktop and Orange Pi display acceptance tests are still required.
