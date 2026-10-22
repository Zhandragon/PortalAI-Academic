# Mission review instructions — 2026-10-22 r2

A paused mission or scheduled run needing review now has an **Additional
instructions** editor and **Reviewed: additional instructions** button in
Missions and access. Enter a correction or answer to the reported problem.

The saved guidance reaches the next plan and remains complete when old execution
history is compacted. Edit it to replace the current guidance; previous versions,
the reviewed problem and pending-action decision are retained in a review ledger.
The original objective, completed work, remaining budget and access mode remain.
Guidance applies to the current mission/run, not future occurrences or existing
subtasks. Empty or oversized instructions and stale reviews are refused.

The compact Schedules layout also keeps all actions visible at 1220x668 in
every access mode. Template selection and Use mission share a row, State and
Source filters share a wrapping row, and Create paused schedule joins the
action row. Saved lists and details still expand with the window.

When an action's outcome is uncertain, **Unresolved: save guidance only** retains
the review gate. Inspect its actual outcome and explicitly choose skip or allow
retry/replan before continuing. Retry permits a fresh plan; it does not execute
the saved action immediately. Stop remains effective until Resume. An unarmed
mission needs Run until finished; a disabled schedule needs Enable. The schedule
Enable button now becomes available when its active run has been reviewed.

Drafts survive refresh, theme changes and switching selection while the sheet
remains open. The current guidance is limited to 8000 characters; a mission
retains up to 256 review versions. If its critical input cannot fit the model's
context, planning stops for review without executing an action.

## Installation

Restart an updated host normally when idle. These clean installers target a new
folder; never overlay one onto an existing account installation. Full model
choices and Academic standard-only restrictions remain separate. All previous
web tools, multiagent ports, direct-chat priority, source filters, timeline fixes
and Projection features are retained. HA/Projection binaries are unchanged from
r1; this update adds no dependencies or new HA receiver version.

| Platform | Installer | SHA-256 |
| --- | --- | --- |
| Windows | [PortalAI-Academic-Windows-Installer-20261022-r2.zip](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r2/PortalAI-Academic-Windows-Installer-20261022-r2.zip) | `7076cd37a288ac9ab81a779ba141433417ac86b91bbf2ffc20ae0aad83f9a169` |
| Linux | [PortalAI-Academic-Linux-Installer-20261022-r2.tar.gz](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r2/PortalAI-Academic-Linux-Installer-20261022-r2.tar.gz) | `04e9187a49db28db94f79149065c698e3dd1fe73d837e1128cf5c9ef21ad2c1f` |
| Mac | [PortalAI-Academic-Mac-Installer-20261022-r2.tar.gz](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r2/PortalAI-Academic-Mac-Installer-20261022-r2.tar.gz) | `6498e3e689363e4931215980eb6dad708ac8717f299dd4be7753a70da3a9be73` |

## Verification

- 131 local tests ran across 14 suites: 130 passed and one existing test was skipped.
- Real Tk tests exercise guidance submission, uncertain effects, draft retention,
  stale review refusal and schedule re-enable. Light/dark UI was inspected.
- Process checks cover controller exclusion, restart, crash cleanup, no replay
  and late planning after Stop. Tests use disposable records, not owner tasks.
- Both exact Windows payloads pass the new review tests and context, schedule,
  supervisor, chat priority, layout and Stop regressions. All six archives and
  payload inventories, unchanged component pins, edition policies, shell syntax,
  source bytes and publication privacy were checked.
- All three Academic setup launchers passed prepare-only extraction with every
  pinned file verified. Linux/Mac scripts ran through Git Bash on Windows.
- The guarded Aoostar updater passed preflight, conflict, account-open refusal,
  partial-write rollback, repeat no-op and private-fixture preservation checks.

Native Mac/Linux UI, physical Aoostar and live-owner-model acceptance remain
recipient checks. [Detailed validation](MISSION-REVIEW-VALIDATION.json).

## Reported Aoostar evidence from the preceding handoff

The user relayed Aoostar Codex's report that the host and Projection updates were
installed and checksum-verified, 32 installed-feature checks and a 798-file
source scan passed, the CPU model restored after tool handoff, and Stop/restart
kept scheduled work paused. Those logs were not independently inspected here.

Two end-to-end tests remained unsuccessful: the 1.7B model attempted extra tools
outside the test allowance (blocked) and repeated a planning step until
`needs_review`. These remain model-behavior limitations, not passing acceptance
results. The new review entry provides corrective user guidance; it does not
claim to fix those model failures. Preserve tool limits and uncertain-effect
review guards. HA 0.5.12 still needs deployment on the HA server. These reported
results concern the preceding handoff, not acceptance of this r2 update.
