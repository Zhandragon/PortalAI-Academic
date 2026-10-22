# Executable recovery and scheduled missions

Executable recovery â€” PortalAI Full and Academic, 2026-10-22 r4

PortalAI checks its registered public runtime files after login and periodically
while open. Missing files trigger a review popup. Where readable, an exact Avast
quarantine metadata match is shown; other missing files are labeled as possible,
unconfirmed antivirus interference. It does not read quarantine payloads.

Review your antivirus alert. If you trust the installed component, temporarily
pause the relevant shield, then click Proceed â€” restore backups. Re-enable
protection immediately afterward. A matching SHA-256 identifies the original
installation file; it does not prove an antivirus detection is a false positive.
Repeated quarantine should be reviewed with the security vendor. PortalAI does
not change security settings or add exclusions.

Right-click Controls or Maintenance and select Repair missing executables for
a manual check. A PortalAI administrator is required for an in-app repair of
shared runtimes. Stop, logout and Exit cancel stale repair requests. Repair
does not enable a schedule, replay an action or start an engine.

Windows: Repair PortalAI.exe in the application folder works independently of
PortalAI.exe and bundled Python. Use it when either is missing. Its read-only
--check option reports missing registered paths; --restore explicitly requests
repair. This native .NET helper requires the Windows runtime already used by
the installer and does not alter PowerShell execution policy.

Backups live in Maintenance/ExecutableRecovery as ordinary ZIP files plus an
installation fingerprint manifest. Windows installers create them after full
selected-payload verification, before publishing the installation. Native
installers record initial LLM backends and interpreter binaries after verified
archive extraction and native compilation. Mac locally built binaries have
installation fingerprints, not vendor-signed binary attestations. Space checks
include a conservative allowance for these backups. Identical files share one
archive; model weights and private account data are not backed up here.

Repair verifies archive inventory, byte size and SHA-256 before restoration,
refuses linked/out-of-root/private paths, and never overwrites existing files.
A missing or corrupt backup cannot be repaired by this feature. Files installed
outside the supported installer/update inventory are not automatically enrolled.
There is no automatic download fallback or repeated automatic restoration.

Local validation used harmless missing/corrupt-file fixtures, actual Tk buttons,
Stop cancellation, the compiled independent Windows helper without Python, and
both installer engines with a small verified payload. It did not deliberately
make antivirus quarantine a new file. Physical Mac/Linux antivirus integration
has not been tested; only Avast has a metadata-specific detector.

Scheduled missions â€” startup and activity, 2026-10-22 r4

Due schedules previously could save a running status while the supervisor
waited indefinitely for an engine that nobody started. The supervisor now
dispatches the owned worker; guarded engine preparation honors the saved model
policy. A fresh account's media-log directory is created before startup logging.
The latter issue was independently identified by Aoostar Codex during testing.

The Persistence views now have Overview, Live activity, Results, Action history
and Details, with current/previous run selection. Activity shows model loading,
streamed response content, actions and timestamps. Controller/worker liveness
and heartbeat identity determine whether it is actually running. A saved status
alone is not proof of activity. Model previews are uncommitted output; only a
complete, validated response can execute actions. Notes and outputs are readable
separately from raw structured details.

Foreground-chat priority, captured login, Stop/Exit epochs, GPU lease, worker
ownership and pending-action/no-replay rules remain. Enabling a future schedule
still waits until its scheduled time. Stop/Exit disarms; explicitly Enable when
you intend to run again. Model output quality and completion of arbitrary user
missions are separate from scheduler operation.

The first donor real-model attempt was interrupted by an Avast IDP.Generic
quarantine of the CPU launcher. After the user reported disabling shields, the
launcher was restored from an identical bundled file matching its recorded
SHA-256. A subsequent actual 1.7B CPU test in a fresh authenticated disposable
account passed cold startup, two scheduled occurrences across controller restart,
visible streaming, readable note/completion results, Stop during inference and
durable no-revival after Stop. The test account was verified sealed afterward.
Owner missions and settings were not read, replayed or changed.

Unit/Tk and real-process checks cover dispatch, malformed/truncated streams,
Stop/login cancellation, pending effects, status, run navigation and chat model
handoff contracts. Physical Aoostar acceptance remains separate: use the new
source-aware handoff and preserve any newer Aoostar fixes during merge. Native
Linux/macOS package checks are not physical desktop/model validation.

## Validation in this release

The local Full regression suite ran 193 tests (one expected skip); the Academic source suite ran 164 (one expected skip). Recovery-specific tests exercised verified installation pins, corrupt/missing backups, existing-file preservation, cancellation, path/ZIP constraints, actual light/dark Tk controls, and the compiled standalone Windows repair helper. Both installer engines created recoverable backups from a small verified installation payload; space accounting includes those backups. Package verification checks every changed source member, outer hashes, original dependency/model pins, and native file modes/links.

A fresh authenticated disposable account passed cold 1.7B CPU startup, two recurring runs across controller restart, actual streamed output, readable results, Stop during inference, durable disarming and verified sealing. A separate test passed actual inference before and after healthy engine stop/restore. Another small-model repeat entered needs-review; these tests do not guarantee successful model planning for every objective. The owner's existing mission was not replayed.

For antivirus-specific instructions, consult [Avast Quarantine](https://support.avast.com/en-gb/article/use-antivirus-quarantine/) and [Avast Core Shields](https://support.avast.com/avast/en/us/home/current/solutions/antivirus-shield-settings). The popup identifies only exact available Avast metadata; a missing file alone does not establish an antivirus cause.
