# Optional privacy and accounts — Windows r63

Fresh installations offer an administrator account with independent **Encrypt
saved account data** and **Require a password** choices, or **Use without an
account**. Account-free mode opens a persistent shared, unencrypted workspace
without a username/password prompt. Its internal profile identifier keeps normal
chat, history, tools, scheduling, exports and recovery routing working.

Existing installations retain their current settings. Administrators can open
**Accounts → Privacy and sign-in**, select an enrolled account, choose its storage
and password requirements, and apply the change. Administrators and standard users
may have different policies. Account-free startup can be assigned to a selected
profile; other accounts are retained and remain available through Change current
user. Turn off shared startup in this screen to return to the account chooser.

| Storage | Password | Meaning |
| --- | --- | --- |
| Encrypted | Required | Password-wrapped profile key; saved payloads encrypted while closed. |
| Encrypted | None | Ciphertext is retained, but its key is public on the SSD; anyone with the drive can unlock it. |
| Plaintext | Required | Password locks the interface. Workspace files, recovery copies and saved service credentials are readable on disk. |
| Plaintext | None | Shared readable files without a password prompt. |

A passwordless administrator exposes administrator access to every profile it
can manage, including encrypted accounts. This consequence appears in the UI.
Guest retains its existing public-key behavior. Account passwords do not protect
an open workspace from the host OS. Internal registry metadata retains the
existing authenticated envelope format even in account-free mode; its public
unlock key provides no confidentiality. User payloads in plaintext mode are not
silently encrypted. Separately passworded user documents and legacy tool vaults
retain their own protection.

## Verified conversion and interruption recovery

Apply first locks the app, stops its owned writers, saves the current workspace,
and closes its account session. Conversion prepares a separate profile, rotates
its data key and the registry master key, converts account connections, and verifies every copied file before
replacing the live profile and publishing the new registry. The 80 GiB free-space
floor includes temporary copies; a conversion can be refused on a large profile
until more free space is available. No model/runtime files are involved.
Other administrators retain their passwords and profile keys; their registry
access is rewrapped for the new master. The current registry recovery copy must
also verify before cleanup can finish.

Complete historical recovery generations are decoded into deduplicated history
under `Workspace/Data/PrivacyHistory` and protected by the destination policy.
`versions/*.json` maps original paths to SHA-256-addressed `objects/*.data`.
`keys/*.json` contains only that profile's previous data keys, for historical
profile-bound connection envelopes. It never archives the administrator master
key or other accounts' registry records. Original storage inventories contain
paths, sizes and hashes, not extra nested vault copies. Unknown, corrupted or
unreferenced recovery entries stop conversion for review instead of being lost.

`Private/privacy-change.json` blocks normal login after an interrupted conversion.
The login screen offers **Recover privacy change**. Before the registry commits,
rollback uses the original administrator credentials; finish uses credentials
under the prepared settings. After commit, finish uses the current administrator
credentials and resumes verified cleanup. Blank passwords work when that
administrator is passwordless. An interrupted initial preparation must roll back.
The app does not infer success from a renamed directory or discard uncertain data.

Enabling encryption also converts this profile's retained plaintext history.
It cannot retroactively encrypt external backups or guarantee physical erasure of
previous SSD blocks. Adding a password to a formerly public encryption key uses
this key-rotating conversion, not ordinary password rewrapping.

## Plaintext lifecycle

Plaintext workspaces remain in place after verified shutdown. `PlainRecovery`
stores checksum-verified incremental copies and reuses unchanged blobs. External
edits or intentional deletions remain authoritative; opening a profile never
silently resurrects deleted plaintext files. A crash retains the latest workspace
files and requires the same writer-stop and account-epoch checks before reuse.
Checksums detect corruption; they do not authenticate against a filesystem owner.

There are no new dependencies, downloaded models or persistent services. UI work
uses the existing background writer coordinator and coalesced progress updates.
Conversion streams file payloads in bounded chunks; startup does not load an LLM.

## Source and validation

Core: `Agent/local_accounts.py`, `profile_workspace.py`,
`plain_profile_workspace.py`, `profile_runtime.py`, `account_privacy.py`,
`account_connections.py`, `profile_migration.py`, `profile_reset.py`,
`admin_profile_access.py`. UI: `ControlCenter/account_privacy_ui.py`,
`account_ui.py`, `account_gate.py`, `account_switch.py`, `help_catalog.py`.

Synthetic tests cover all four account modes, account-free save/reopen, mixed
profiles, data/connection preservation, both conversion directions, historical
deduplication, unknown-file refusal, interrupted copy/swap/cleanup recovery,
plaintext export/reset, interrupted harvest, narrow dialogs and theme compatibility.
The release validation report records executed counts and any limitations. Real
owner accounts are never used as fixtures or automatically converted.
