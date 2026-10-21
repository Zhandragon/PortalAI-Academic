PortalAI Projection - Windows and Linux companion
=================================================

macOS Projection is NOT supported yet. This optional companion connects an
existing PortalAI installation to Home Assistant; it does not install PortalAI.
Choose the actual Academic application folder when using the Academic edition.

Windows: open PortalAI-Projection/Start Projection.cmd.
Linux: sh "PortalAI-Projection/Start Projection.sh" in a graphical desktop.
Keep PortalAI-Projection and PortalAI HA Setup beside each other on the same
drive as PortalAI. Both companion launchers use their bundled Python runtimes.

Linux requires x86-64, X11/XWayland, a TrueColor display, Linux 5.14+, an
executable mount, and systemd user cgroup v2 delegation with memory control.
Physical Linux desktops and end-to-end HA Cloud deployment are unvalidated.
Both hosts need a signed-in, unlocked desktop. macOS and ARM Linux hosts are
not supported by this Projection package.

1. Create a Projection connection with your verified HTTPS Home Assistant
   origin, your installed Academic application folder, and a new projection
   unlock password (at least 12 characters). Click Create / Unlock.
2. Copy the generated PUBLIC pairing JSON and public device_id.
3. On a trusted administrator device, install the included HA 0.5.11 + Recovery
   0.1.0 integration using PortalAI HA Setup/Install PortalAI HA.cmd (Windows)
   or Install PortalAI HA.sh (Linux). HA must already be installed/onboarded;
   provide its writable config directory/share and public device_id. Read
   Setup Files/HomeAssistant/README_FIRST.txt before configuring your server.
4. Check the HA configuration, restart HA and reload its browser/app.
5. In HA Developer Tools > Actions, call portalai_projection.pair_device with
   the PUBLIC JSON in pairing_request, then portalai_native.allow_state with
   device_id. Skip this if the installer's optional first-pairing flow succeeded.
6. Start projection, then Open PortalAI locally through the companion. Sign in
   to PortalAI and open the PortalAI Native sidebar or Desktop/Quick Chat in HA.

Full guide: https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/PROJECTION.md

Projection uses outbound HTTPS and stores its connection/device key encrypted.
The connection manager never requests an HA password or API token. HA admin
approval and PortalAI account sign-in are separate. Select your own Academic
installation; the suggested sibling folder may not match its installed name.

Stop projection does not sign out of PortalAI or seal its workspace. Use the
normal PortalAI Accounts/Exit controls and wait before removing the drive.
Do not use Force Shutdown as a normal exit. The optional Start HA Recovery.cmd
helper is Windows-only and needs separate local arming and HA pairing; see
PortalAI HA Setup/Setup Files/HomeAssistant/RECOVERY.txt.

This clean distribution contains no saved connections, pairing identities,
accounts, logs or captured screens. Connection/state folders are created when
needed. Third-party runtime licenses remain in their bundled distributions.
