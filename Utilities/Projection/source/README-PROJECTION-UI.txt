PortalAI Projection UI - 20261022-r1

Minimize to the dark PortalAI emblem; left-click it to reopen. Right-click the
tray icon or inside the launcher window for themed actions and explanations.
Start/Stop projection controls the HA connection. Start local PortalAI opens
the selected portable app without requiring an HA connection. Exit disconnects
projection before closing. Normal PortalAI account and root ownership remain.

Appearance provides light/dark modes and custom accent/border colors. Documentation
contains setup, pairing, tray, platform and troubleshooting instructions.
Preferences are stored in state/ui-settings.json, separately from encrypted
Connections/. Preserve both directories when updating. Minimize leaves an
unlocked connection available. The dark tray emblem stays the same in either theme.

Windows tray and actual Tk tests passed. Mac uses the menu bar (Control-click is
supported); Linux uses Tk's X11 tray. Missing tray support keeps a taskbar window.
Native Mac/Linux and physical HA acceptance remain recipient checks.
HA 0.5.12 is included in the sibling HA Setup. It must be deployed to HA separately.
Restart Projection normally to activate; do not replace a running companion.
