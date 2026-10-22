PortalAI Home Assistant 0.5.12 + Recovery 0.1.0

Extract this complete folder, then double-click Install Home Assistant.cmd.
The launcher uses ../Runtime/Python/python.exe from the PortalAI distribution,
or installed Python 3.9+ through py -3. Linux: sh install.sh
No Node.js, pip, or internet download is needed for installation.

The wizard asks for the writable HA config folder/share and PUBLIC device ID.
It installs all three integrations and three frontend bundles, configures the
Native UI sidebar, registers modules, and creates Quick Chat, Desktop and
Recovery dashboard views. Standard new HA setups need no manual YAML edits.
Every changed file, including configuration.yaml, has a verified backup.
Other top-level YAML sections, secrets, pairings and .storage are preserved.

Optional: enter your trusted HA URL and privately enter an administrator token
to validate configuration, restart once and wait for PortalAI services. The
token stays in process memory and is never saved, printed, or passed in command
arguments. Optional first-install PUBLIC projection pairing JSON also approves
projection and native state. Leave it blank if already paired.
The installer never opens PortalAI or requests recovery.
Recovery pairing is separate: follow RECOVERY.txt to pair and arm its helper.

This is a one-launch setup wizard. HA must already be installed/onboarded and
its config writable from the installer machine. First-time owner access and
pairing cannot be skipped. Without the optional HA URL/token, check configuration
and restart through HA Developer Tools > YAML. Reload browser/app caches.

CLI:
  python install.py verify
  python install.py plan --config /config --device-id YOUR_PUBLIC_DEVICE_ID
  python install.py install --config /config --device-id YOUR_PUBLIC_DEVICE_ID
On HA with Python and its CLI, append --restart to check/restart automatically.
From a trusted computer with a writable share, append --ha-url https://YOUR_HA.
For first pairing, append --pairing-public-file "public-pairing.json".
Never put the token in an argument or distributed file; it is prompted privately.

UPGRADES / ADVANCED YAML
Canonical URLs:
  /local/portalai-live-v0.5.12.js
  /local/portalai-quick-chat-v0.4.3.js
  /local/portalai-projection-v0.5.12.js
Recognized older PortalAI resource URLs on disk get the compatible new payload
with backups, so older resource registrations cannot load the known broken code.
Unrecognized custom aliases need owner updates.

Automatic merge stops BEFORE writes for existing packages, external includes
in edited frontend/panel/Lovelace sections, anchors/aliases, duplicate keys or
conflicting dashboard URLs. For these advanced existing layouts use:
  python install.py install --files-only --config /config --device-id YOUR_PUBLIC_DEVICE_ID
Then merge portalai/examples/0.5.12/*.yaml into the existing layout, validate and
restart. File-only mode does not edit configuration or legacy resource aliases.
Copy only frontend JS into public www; keep installer, source and backups private.

ROLLBACK
The installer prints an exact rollback command and private backup path:
  python install.py rollback --config YOUR_CONFIG --backup PRINTED_RELATIVE_PATH
All originals and current checksums are verified BEFORE any restoration.
Later user edits are not overwritten. Validate and restart HA after rollback.
Initial pairing through HA APIs is separate from file rollback and is never
silently revoked. Use the integration's remove_device/revoke_state if required.
For interruption: ensure no installer remains running; preserve the journal,
remove only the stale .portalai-installer/install.lock, then run rollback.

FEATURES
Attachment controls clear their loading notice after a completed/failed read
and rediscover the file picker when a blocking host dialog closes. Existing
host dialog checks still apply; 0.5.12 requires no additional host protocol.
Uploads use larger chunks when the updated Aoostar GUI and companion advertise
support; old hosts continue in compatibility mode. See AOOSTAR_HANDOFF.txt for
host compatibility. Install HA backend and frontend together for the
10-second grace after hiding the app. iOS can still suspend/disconnect earlier;
keep HA open until the attachment is added. Persistent background uploading is
not part of this release. Native iPhone app changes would be required.

Local HTTP now supports secure random request IDs and SHA-256 uploads/exports.
Native UI > Chat > Attach accepts a desktop file drop or chooser selection,
adds it to pending attachments, and never sends the message automatically.
iPhone Attach offers Photos/Videos and Files (iCloud / On My iPhone).
One file at a time, up to 20 MiB. Stale/uncertain operations are never replayed.
Desktop projection remains a pixel stream; use Native UI for file upload.
Aoostar reconnect protection and Recovery 0.1.0 are retained.

See AOOSTAR_HANDOFF.txt, VALIDATION.txt and RECOVERY.txt.
STABILITY.txt and MERGE_NOTES.txt are historical 0.5.3 provenance documents.


0.5.12: pair with the matching Aoostar history/vision/media host update.
See AOOSTAR_HANDOFF.txt for update order and compatibility.
