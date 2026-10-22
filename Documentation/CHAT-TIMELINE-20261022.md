# Direct chat priority, schedule filters and Projection controls — 2026-10-22

Direct chat now pauses background mission/schedule execution. Planning yields
promptly; an already admitted tool finishes its safe checkpoint before chat
begins. A bounded summary is saved to scoped memory, while the complete action
ledger and remaining budget stay intact. The UI reports checkpointing while it
waits. After the reply completes, fails or is cancelled, the existing supervisor
continues work that is still armed/enabled. Explicit Stop, Disable, logout and
uncertain pending effects remain authoritative; completed actions are not replayed.
The same rule applies to chat sent through the HA/projected panel.

Schedules now has a dynamic Enable/Disable toggle and independent State/Source
filters. All origins, User created, Diagnostic and Legacy / unclassified can be
combined with Active and paused, Removed schedules or All schedules. New GUI/CLI
schedules record their origin. Recognized historical self-tests have a legacy
diagnostic label; unknown records are not guessed to be user work. Filtering is
read-only. Saved-mission templates and reversible schedule removal are included.
Missions & Access and Schedules expand their lists/detail panes with the window,
and scroll extents adjust after responsive columns rearrange.

Desktop history could finish drawing after a newly submitted response had begun.
Send/Regenerate now wait for the bounded history drawing to finish, preserving
the draft. Reopened messages show reasoning, response prose, then tool details,
matching the live view. Replacing the history cancels old drawing callbacks.

The response timer now follows queued Preparing, Thinking, Writing and tool
phases, then freezes immediately as Completed, Stopped or Failed. Outstanding
live cards settle on completion. Stop still waits for existing request cleanup.
The host rich API ends reasoning's streaming state when answer text or tools begin.

HA **0.5.12** puts reasoning above the associated answer and tool/media details
below it. Expanded cards retain their state during refresh. An idle snapshot
also settles cached streaming labels. Recovery remains **0.1.0** and protocols,
pairing, account isolation, tool execution and continuation rules are unchanged.

## Installation

Exit PortalAI normally and restart to activate an existing host source update.
Install [HA 0.5.12](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-HomeAssistant-0.5.12-recovery-0.1.0.zip) on the HA host using its included
installer, then reload the browser resources. Updating D: does not deploy to a
remote HA server. The HA payload is included in Windows/Mac setup and as a ZIP
under the Linux installer's Utilities folder.

Clean installers target a new folder and refuse existing account roots.
Full model choices and Academic standard-only restrictions remain separate.
Academic's three setup launchers are rebuilt and pinned to this release.
Projection has a dark PortalAI tray/menu-bar emblem: minimize keeps the connection
running, left-click reopens the window, and right-click shows a themed action menu.
The same menu is available inside the launcher window, with explanations for each
action. Start/Stop projection, Start local PortalAI, Appearance and Documentation
are included. Local start works without an HA connection and uses the existing
account/ownership lifecycle. Exit still waits for projection to stop.

Appearance offers light/dark modes and custom accent/border colors using PortalAI's
native rounded buttons and ornamental borders. Preferences remain separate from
encrypted connections. The Documentation subtab explains pairing, controls and
troubleshooting. When no tray is available, the taskbar window remains reachable.
Windows uses its notification area, Mac its menu bar and Linux Tk's X11 tray.
The Windows native tray and real Tk were tested; native Mac/Linux remain pending.

Complete refreshed companions are in the release for all three platforms. Windows
installers include the companion source plus pinned runtime downloads. Linux/Mac
include the full companion and HA setup under the installer's Utilities folder;
keep those utility folders together and use Browse to select the installed app.

| Platform | Installer | SHA-256 |
| --- | --- | --- |
| Windows | [PortalAI-Academic-Windows-Installer-20261022-r1.zip](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-Academic-Windows-Installer-20261022-r1.zip) | `5634b33afc535b232d06aabbb40ab9670d368221ca70230aa814fda100308249` |
| Linux | [PortalAI-Academic-Linux-Installer-20261022-r1.tar.gz](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-Academic-Linux-Installer-20261022-r1.tar.gz) | `8923a5c9896f631c369f4146734411201d9a93d86e9616ad98234e52f7b54220` |
| Mac | [PortalAI-Academic-Mac-Installer-20261022-r1.tar.gz](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-Academic-Mac-Installer-20261022-r1.tar.gz) | `bff2d3d05f38d9e556ce763b29d48caa14bef28a64d0d72f54ddaed022c4fe26` |

## Verification

- 172 local host tests passed, including withdrawn real Tk timeline tests,
  completion/continuation, loading, native rich reads, remote chat commands,
  Stop/writer checks and layout tests.
- 92 JavaScript and 71 HA Python tests passed. A real bundled Chromium DOM
  fixture verified order, disclosure retention, tool placement and idle labels.
- Exact Full and Academic Windows payloads passed timeline, completion, loading
  and rich-chat tests. Six archive/payload inventories and runtime pins, Windows
  installer plans, native shell syntax and Academic policy were checked.
- Exact Academic launchers passed prepare-only extraction and all pinned-file
  hashes. Native launchers were exercised through Git Bash on Windows.
- Aoostar updater checks covered read-only preflight, conflicting source, active
  session refusal, verified recovery/application and repeat no-op.

The older zoom fixture lacked the current `hydrate` keyword in its mock. Its
18 tests passed with that mock corrected in memory; shipped production code
and the original fixture were not changed for that unrelated mismatch.
Physical Aoostar, native Mac/Linux execution and live HA deployment remain
recipient checks. [Detailed verification](CHAT-TIMELINE-VALIDATION.json).

Priority/filter verification covers real OS locks, interrupted loopback planning, checkpoint memory, no replay, explicit Stop, cancellation, reply failures, real authenticated remote chat admission, dynamic schedule toggles/filters and growing/shrinking Tk panes. The existing process smoke also verifies supervisor exclusion, restart, crash cleanup and late-plan Stop. Both exact Windows payloads pass the priority, schedule, supervisor, chat handoff and remote-command suites. Native Mac/Linux and live owner-model execution were not run.

Known test-fixture limits: the retired mTLS bridge fixture fails its local certificate handshake on both the unchanged baseline and updated source. Current HA/native chat paths pass their separate tests. The older settings fixture requires its Tests directory in the isolated import path; it passed with a test-only launcher wrapper. Shared chat fixtures now use disposable roots, including the authenticated fixture root for remote admission. No production authentication or TLS check was weakened.

Projection checks: 14 local UI/tray tests, the same 14 against the exact Windows companion runtime, six existing lifecycle contracts and 16 synthetic Mac contracts passed. The companion updater passed six guard/preservation/rollback cases. Published Linux interpreter/loader executable bits were retained and checked. No owner connection or account was used.

[Windows Projection bundle](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-Projection-Windows-20261022-r1.zip) · SHA-256 `40eae62e5d5bead99d5782f94f955bc22d738be01e63b2b5a7a0e99356ebc531`.

[Linux Projection bundle](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-Projection-Linux-20261022-r1.tar.gz) · SHA-256 `4d6234ed97597e4ac4f6b7e23dbf1858910b01a7ab63128ad226b8cfede7a4b3`.

[Mac Projection bundle](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.22-r1/PortalAI-Projection-Mac-20261022-r1.tar.gz) · SHA-256 `2cc8438bbb5d9cf52aa6753a34ebd2781292a92f41181e9b1da8f1a888a07c26`.

Native adapter references: [Microsoft notification area](https://learn.microsoft.com/en-us/windows/win32/shell/taskbar), [Apple status items](https://developer.apple.com/documentation/appkit/nsstatusitem), [Tk systray](https://www.tcl-lang.org/man/tcl8.7/TkCmd/systray.html).
