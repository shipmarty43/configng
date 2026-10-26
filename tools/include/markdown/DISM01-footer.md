### Display manager

**System → Desktop → Display Manager** shows the configured default, installed
supported packages and systemd's current display-manager service. These may
differ until the package configuration and service transition are complete.

Configuration supports installed **LightDM, GDM3 and SDDM** packages on
Debian/Ubuntu. Selecting a package starts its interactive `dpkg-reconfigure`
dialog; the package manages debconf and service registration. The selected
package opens the chooser; it is not itself a promise that it became default.
The resulting default and live service state are shown after completion.

**Save work first. Package scripts may restart the login service and end
graphical sessions.** The menu asks for confirmation, defaulting to Cancel.
Use a text console or SSH when changing the DM. No next-boot-only guarantee is
made. No manager is installed automatically, and autologin is not enabled.
The existing desktop installation/autologin functions remain separate.

```sh
armbian-config --api module_display_manager status
armbian-config --api module_display_manager installed
armbian-config --api module_display_manager reconfigure lightdm --confirm-session-interruption
```

The last command intentionally opens an interactive package dialog and may
interrupt desktop sessions; it is not an unattended provisioning interface.
For rollback, reconfigure an installed previous DM from a text console/SSH and
verify both the default and the service. Errors from package configuration are
propagated. Tests mock package/service operations and do not reconfigure the host.
