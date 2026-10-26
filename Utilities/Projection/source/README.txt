PortalAI Projection — standalone portable companion
===================================================

Windows: double-click Start Projection.cmd. Linux: run Start Projection.sh
from a graphical desktop (or sh "/path/to/PortalAI-Projection/Start Projection.sh").
Everything stays beside PortalAI on the SSD, including separate bundled Windows
and Linux Python/Tk/TLS runtimes (about 232 MB combined). No host Python/Node,
OS service installation, inbound LAN port or HA API token is required.
Linux x86_64 requires X11 or XWayland, a TrueColor display, Linux 5.14+ and a
delegated cgroup v2 with memory control. The launcher requests a systemd user
scope; it never uses sudo, enables OS features or falls back to killing by PID.
Both hosts need a signed-in, unlocked interactive desktop. Physical Linux
desktops remain unvalidated; actual offline Linux execution has passed.

PortalAI and OpenClaw are entirely separate. This module does not use, change,
restart or depend on OpenClaw, its agent, scripts, integration or RDP connection.

First install on each Home Assistant instance (trusted device)
-----------------------------------------------------------
1. Back up HA configuration. Open ../PortalAI HA Setup/Install PortalAI HA.cmd
   and choose Install for a writable HA config/share, or Prepare for a ZIP to
   transfer to a trusted HA device. The complete package is under that folder's
   Setup Files/HomeAssistant. It includes Native, Desktop, Quick Chat and the
   separate Recovery integration. Use the public pairing/device ID only.
2. Let the installer configure a standard HA layout, then validate/restart HA
   and reload the browser/app. Advanced YAML layouts stop before writes and
   need the documented manual merge. Existing pairings are preserved.
   This folder's HomeAssistant receiver 0.3.0 files are historical fixtures;
   do not install them over the complete current package.
3. On the SSD launch this module. Enter a connection name, the HTTPS HA Cloud
   origin (for example https://YOUR-INSTANCE.ui.nabu.casa), and the PortalAI
   folder. Create a projection unlock password of at least 12 characters.
   This is NOT your HA password or PortalAI password.
4. Click Create / Unlock. Copy the public pairing JSON displayed below, or use
   its .public-pairing.json file in Connections. On HA, signed in as an admin
   on a trusted device, run portalai_projection.pair_device from Developer
   Tools > Actions and paste that JSON into pairing_request. The receiver stores
   only its public key. This approval does not grant the device HA API access.
5. Use the generated card YAML or dashboard.example.yaml for a dedicated panel.
   Replace device_id with the displayed value. Add the separate restart/force
   buttons from master-buttons.example.yaml to your existing master dashboard.
6. Click Start projection. Then use Open PortalAI locally, or Open PortalAI in
   HA. Log into the real PortalAI sign-in sheet through the streamed interface.
   On Windows, Full Restart can adopt an already-running PortalAI after its
   normal close/seal. On Linux, first close any GUI launched outside Projection
   locally, then use Open PortalAI here; Linux captures only windows reported
   by that GUI's optional input adapter.

A URL and HA login alone cannot install the receiver. The one-time receiver
installation and administrator pairing are required on every HA instance.
Home Assistant Cloud must permit the installed custom endpoint; physical HA
Green/Nabu Casa deployment is still unvalidated. No HA credentials should be
entered in this app or copied to this drive. Use HA's own sign-in on your phone
or another trusted device to change your HA login, revoke a device or approve
a destination. No new HA account is needed.

Changing destination and moving the SSD
--------------------------------------
Stop projection and wait for it to exit, unlock the saved connection, edit the
URL/folder and Save changes. A different HA must separately approve its public
key. Use New for an independent pairing identity. Remove the old device from
the previous HA with portalai_projection.remove_device when it should no longer
be usable. Change unlock password re-encrypts the same connection/device key.

PortalAI paths are relative to this folder, so changing the SSD's drive letter
works without embedding D:. Keep both folders on the same drive. Launch the
module again after moving/replugging it. It connects outbound over verified
HTTPS to the selected Cloud URL; it does not need the recipient PC's former
LAN address, Tailscale identity or an incoming port rule. Existing restrictions
on access from the AI computer to LAN devices stay in place. A changed host
may still block outbound HTTPS or lack a usable desktop session.

The input endpoint uses a per-user folder (Windows SID or Linux UID). Connection
files are encrypted; local NTFS permissions may still need ordinary access
adjustment when a different Windows account mounts the SSD. This is not an
administrator service, sandbox, or guarantee of compatibility on every host.
Linux mounts must allow execution of bundled binaries; a noexec mount cannot
run this portable bundle. If the file manager requires executable permissions,
enable Run as Program for Start Projection.sh and executable permission for
Runtime/LinuxPython/run-python, Runtime/LinuxPython/bin/python3 and
Runtime/LinuxNative/ld-linux-x86-64.so.2. Do not relax Private/profile permissions.
ARM Linux, native-Wayland-only sessions without XWayland, missing user cgroup
delegation, locked/headless desktops and unusual visual formats are unsupported.

Security boundary
-----------------
Connections contain an encrypted URL, relative PortalAI path and P-256 device
key using AES-GCM with a password-derived scrypt key. The unlock password and
unlocked device key remain in the projection processes only; they are not
passed to PortalAI in arguments/environment or copied to HA. HA passwords,
cookies, access tokens and refresh tokens are never accepted or stored.

The device key authorizes only this projection endpoint: upload a bounded PNG,
upload status, acknowledge a dispatched command and receive approved desktop
input. It does not authenticate to HA REST/WebSocket APIs or allow calling HA
services/entities, reading HA history, running HA shell commands or installing
HA integrations. HA administrators alone can view/control/pair/revoke/restart.
The protocol rejects replayed challenges/polls and expires queued inputs.

Encryption protects closed connection files at rest. An unrestricted program
running as your OS user can alter this module or inspect its memory while
unlocked. It may interfere with the projection or steal its limited device key;
that key still is not an HA API credential. No portable same-user application
can enforce secrecy against that user without OS isolation. Verify receiver
code ZIP checksums before installing it on a trusted HA device. A public pairing
request is not executable code and contains no private key or HA login.

The server renders only bounded PNG pixels/literal text; no executable web page
from PortalAI runs inside HA. PNG header dimensions are checked before browser
decoding. Screen frames and key input are not persisted to module logs or HA
storage. HA keeps approved public keys and latest operation status. A network
failure leaves an action's outcome uncertain: input is never replayed blindly.

Controls and viewing
--------------------
Auto: portrait iPhones use the existing expanded compact chat; landscape uses
the full GUI. Windows and iPad use full GUI. Both Pro Max sizes have local
viewport previews, not physical iOS validation. Layout can be overridden.
Phone orientation prefers physical orientation over the on-screen keyboard's
viewport size. Same account, chat and model/effort settings survive rotation.

Portrait Message PortalAI uses the existing chat Send path. Tapping the screen
switches to masked screen typing for account/settings fields. Keyboard:
screen/chat switches back. Direct chat refuses open account/shutdown/modal
dialogs and busy chat. More reveals window selection, zoom/pan and right-click.
Native file dialogs browse the SSD/Aoostar, not the phone. External apps,
Explorer/browser windows, clipboard, audio and microphone are not forwarded.

One shared desktop login, with one HA viewer at a time. Disconnecting the card
or stopping projection does not log out/seal PortalAI. Use PortalAI Accounts /
Exit for its verified normal lifecycle. A stopped/disconnected feed becomes
offline after its bounded freshness timeout (up to 15 seconds).

Full Restart closes all verified PortalAI GUI instances normally, waits up to
180 seconds for owned processes and same-epoch profile sealing, then reopens.
It never forces termination on timeout. A crashed GUI with no remaining workers
may open the normal authenticated recovery screen without claiming sealing.
Force Shutdown requires explicit UNSAFE SHUTDOWN confirmation; it terminates
verified owned processes, preserves recovery journals and prevents old armed
missions/schedules from resuming. It does not reopen automatically. Never delete
PortalAI/HomeAssistant/state/forced-stop.json to undo an interruption.
Linux force shutdown retains the existing delegated-cgroup and pidfd checks.
Workers belonging to a different/unverifiable scope are refused, not killed
using a broader scope or guessed PID. Start PortalAI through this companion
to share its delegated scope. Refused/failed operations are reported in HA.

Tests and current deployment status
----------------------------------
Receiver installation, real HA Cloud routing, physical iPhone/iPad operation
and live production model/account restart are NOT yet validated. Local tests
exercise encrypted settings, HTTPS/no-HA-credentials transport, pairing/replay/
revocation and actual disposable Windows GUI capture/input/login/sealing.
Offline Linux tests cover bundled UI/runtime, outbound HTTPS, owned XComposite
capture, Tk typing/buttons/Return, dropdowns/menus, resize, normal close callback,
exact process identity, pidfd termination and delegated worker cancellation.
See VALIDATION.txt for the final evidence and remaining steps. Do not use the
older PortalAI/HomeAssistant inbound bridge package; it has been superseded.


Portable Utilities layout (October 14, 2026)
This companion now lives at Utilities/PortalAI-Projection on the portable drive.
Start it with Start Projection.cmd in this folder. The main PortalAI folder stays
at the drive root. New connections suggest that installation automatically;
Browse still selects an explicit installation. Saved paths are relative to this
companion and follow drive-letter changes when the whole drive layout is retained.

Existing encrypted connections and public pairing files were preserved unchanged.
After this folder move, unlock the EXISTING saved connection normally, Browse to
the main PortalAI folder at the drive root, and click Save changes. Do not select
New: updating the existing target retains the projection key and HA approval.
Then Start projection; use Open PortalAI locally to load the native/input adapters.
No general HA credentials or wider network access are required.

The optional factory-reset launcher is ../PortalAI-Reset/PortalAIFullReset.exe.
It is installed only; no reset was performed during this relocation. It permanently
discards managed accounts/data/pairing only after typing CONFIRM and clicking Confirm.
Cancel makes no changes. See that folder's instructions before deliberate use.

Upload v2 update - October 15, 2026 (HA 0.5.7)
The host GUI and this companion support negotiated 1 MiB attachment chunks.
The file limit remains 20 MiB with account/form binding, exact offsets and
SHA-256. Native UI/state/chat/rich/media and viewer-demand protocols stay intact.
HA 0.5.7 adds a 10-second grace on hiding the app, but iOS can still suspend
before completion. Keep HA open until attachment admission finishes.

After updating: normally close/reopen PortalAI and sign in; stop/start
projection in the unlocked companion (or close/reopen Start Projection.cmd
and unlock its existing connection). Use the usual lifecycle and wait for
sealing; no Force Shutdown, recovery reset or new pairing is needed.
Upload v2 is advertised only when the running GUI and companion support it.
The Recovery helper remains separately paired/armed and unchanged.
Current merge evidence: Handoffs/HA-0.5.7/INSTALLED.txt and VALIDATION.txt.

HA installer refresh - October 16, 2026 (0.5.8)
The complete installer under ../PortalAI HA Setup now ships HA 0.5.8, fixing
the browser timer receiver error that could block Connect in 0.5.7. The host
upload-v2 patch is unchanged and already installed. A host that loaded that
patch needs no additional restart for this HA-only correction. Keep existing
connections and pairing. Recovery remains 0.1.0. The old HomeAssistant receiver
files here are historical fixtures; use the complete current installer.
See Handoffs/HA-0.5.8/INSTALLED.txt for tests and attributed live HA status.

HA 0.5.9 attachment Send - October 16, 2026
The current complete HA installer is ../PortalAI HA Setup (0.5.9 portable-1).
This companion now forwards negotiated pending-attachment Send support. The
matching host controller is installed, preserving current account-dialog and
worker-admission guards. Normally close/reopen PortalAI, sign in and stop/start
projection to activate. Pending unsent selections may need selecting again.
Keep existing pairing. Recovery remains 0.1.0. Rich error stage diagnostics and
long-picker reconnection are in HA; see Handoffs/HA-0.5.9/INSTALLED.txt.


Current HA release: 0.5.11.
HA 0.5.11 compatibility
The clean installer includes the matching host history, preview and vision UI code.
Use ../PortalAI HA Setup/Install PortalAI HA.cmd for the matching HA receiver.
Create your own account and pairing; no existing connection or account is included.
Existing hosts require a normal PortalAI restart/sign-in and Projection worker restart.
Native state v2, native UI 1, upload v2, crypto and Recovery 0.1.0 are preserved.
