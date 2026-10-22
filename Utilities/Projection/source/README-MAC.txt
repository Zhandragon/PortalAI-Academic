PortalAI Projection for Mac - 2026.10.21, build 1

Apple silicon and Intel, macOS 14 or newer. Built on Windows; native Mac
acceptance is pending. Use a writable executable Mac-compatible volume and a
signed-in, unlocked graphical desktop. Sleep, logout and drive removal interrupt
projection. No host Python, Homebrew, Node or compiler is needed for this utility.
PortalAI's separate full Mac installation retains its existing prerequisites.
This is an unsigned portable command bundle, not a notarized .app. Review any
macOS download/security prompt through its normal interface; the launchers do
not disable Gatekeeper or remove quarantine flags.

Keep PortalAI-Projection and PortalAI HA Setup together inside a Utilities folder
on the same drive as your PortalAI Mac installation, OUTSIDE the PortalAI root.
Do not merge this public package over Connections, state or an existing utility.
Use a fresh folder for a new copy. Existing encrypted keys/pairings are private.

1. Open Check Mac Runtime.command. The first run verifies and unpacks the bundled
   native Python/Tk runtime for your architecture on this drive. It checks imports,
   encryption and TLS without contacting HA or starting PortalAI. Keep its report.
2. Existing WebAgents Mac installs: close PortalAI normally and run Update PortalAI
   Mac Host.command. Select the actual installed root. The updater checks exact
   before/after source hashes, holds controller/profile locks and saves verified
   recovery on the same drive. Unrecognized versions require a source merge.
   The new Full r15 / Academic r3 Mac installers already include this adapter.
3. Open Start Projection.command. Create/unlock your connection, choose the actual
   PortalAI Mac folder and enter the HTTPS HA origin and projection-only password.
   Use public pairing JSON to approve this device in HA. No HA token belongs here.
4. Click Screen permission for the Desktop card. macOS may list the bundled Python
   or Terminal in System Settings > Privacy & Security > Screen Recording (or
   Screen & System Audio Recording). Approve it locally, then quit/reopen
   Projection. Capture excludes audio/cursor and other applications. macOS owns
   permission prompts; this utility never bypasses them or changes OS security.
   Native/Quick Chat can work without permission to capture screenshots.
5. Start projection, then Open PortalAI locally and use the normal sign-in.
   An externally opened GUI must be closed normally before this launch so it
   receives the private local input adapter and dedicated process group.

HA side: open ../PortalAI HA Setup/Install PortalAI HA.command. Choose a writable
HA config folder/share or prepare a deployment ZIP for a trusted HA terminal.
This installs the SAME current HA 0.5.12 receiver/cards + Recovery 0.1.0; HA runs
on its existing server, independently of whether the projector host is a Mac.
It preserves pairings and uses the existing verified backup/rollback installer.
Advanced YAML layouts require its documented files-only/manual-merge route.
Optional administrator tokens are prompted only by the trusted installer and
remain in memory. Do not put deployment ZIPs or private connection files in www.

Recover apps: Start HA Recovery.command is a separate, manually armed helper.
It needs independent HA recovery pairing. It can reopen projection/PortalAI login
after an application crash; it never force-kills, signs in or replays tasks.
It cannot recover a Mac crash, sleeping Mac, unplugged storage or missing runtime.
Full Restart still waits for normal same-epoch sealing. Explicit Force Shutdown
uses PortalAI's existing verified owned-group planner and keeps recovery fences.

Multiple agents/SSDs: each independent PortalAI root retains its WebAgents
controller and configurable service-port allocation. The GUI input listener uses
an OS-assigned loopback port. Each companion copy has its own encrypted connection
and public device ID; use a separate copy for each simultaneously projected root.
Do not copy an unlocked/live connection to another running copy. HA pairing and
agent-to-agent pairing are independent. This utility reserves no inbound LAN port.

Capture binds the authenticated Tk client rectangle and process start identity
to exactly one ScreenCaptureKit window belonging to that process. Only that
window is captured; its titlebar is cropped in memory. Ambiguous/changed windows
are refused. Retina and multiple-display coordinate handling need native testing.
macOS-native menu bar/file-picker sheets are not remote-control targets in this
build; use Native controls/upload where available, or complete those sheets locally.
No global Accessibility event injection or desktop fallback is implemented.

Mac acceptance checklist (use a disposable account):
- runtime check on Intel and Apple silicon; screen permission denied/granted;
- create/unlock connection; pair/revoke; Native/Quick Chat and bounded uploads;
- owned Desktop capture/input on Retina and external displays, moving/resizing,
  another app covering PortalAI, no other app pixels or input;
- Stop/login/modal guards, normal Exit and same-epoch sealed restart;
- separate Recovery pairing, disarm, crash reopen, no duplicate controller;
- two roots/SSDs with distinct configured/automatic ports and separate device IDs.

API references used for this implementation:
https://developer.apple.com/documentation/screencapturekit/scscreenshotmanager
https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/sourcerect
https://pyobjc.readthedocs.io/en/latest/supported-platforms.html

Do not describe the synthetic test results as completed native acceptance.

Projection UI 20261022-r1 adds tray, themed menus, Appearance and Documentation. See README-PROJECTION-UI.txt.
