# Source publication and mission recovery audit — 2026-10-29

Audit baselines: Full `d2374e711d44fb61bed394856674b4abd2fb266c` and Academic
`8efe982184bf928686c258f8271ce8e27ab54a18`, fetched directly from GitHub. The
deprecated C: installations were excluded. The mounted D: and E: installations
both identified themselves as **Full 2026.10.29-Desktop-r51**.

## Findings and changes

| Finding | Resolution |
| --- | --- |
| `mission_runner.py` and `mission_supervisor.py` were already uploaded individually, but difficult to discover from the README. Full is private, so unauthenticated tools cannot inspect it. | Added direct links in both READMEs, a [source map](SOURCE-MAP.md), [module index](MODULE-INDEX.md), and [exact mission recovery contract](MISSION-RECOVERY.md). Academic exposes its corresponding source publicly; Full access policy is unchanged. |
| “Stall recovery” described both NativeChat progress assistance and mission process supervision without a single comparison. | Documented the 480-second mission worker lifetime, independent five-second supervisor status heartbeat, new-process recovery, opt-in scheduled replanning, and NativeChat's between-call intervention separately. |
| Result-save error handling could discard `pending_action` from memory after execution, or demote a successfully committed completion when index publication failed. | Reload the authoritative checkpoint before resolving an error at the result-save boundary. Retain unresolved effects; retain committed results; never overwrite corrupt/missing evidence or roll back to `mission.previous.json`. Regression failures were reproduced before the fix. |
| Timeout/log-limit cancellation reported only a generic worker-exit error; a missing error-log file could raise before cancelling the worker. | Named limits and explicit cancellation reasons; unreadable log storage cancels the owned worker. The elapsed-time policy and retry caps are retained. |
| The Windows `Tools/portable_python.cmd` entry point was referenced by current guidance and registered tools but missing from the published application tree. | Published the exact installed wrapper in both Windows edition trees. It resolves the bundled Python relative to its own SSD folder and does not require host Python. |
| Retained PowerShell UI, bootstrap/hotfix/diagnostic sources and installed script variants were missing from the matching published paths. | Preserved 23 additional exact source versions in the Full repository's [SupplementarySources/Installed-20261029](https://github.com/Zhandragon/PortalAI/tree/main/SupplementarySources/Installed-20261029) (approved Full access required), individually browsable with hashes and purpose labels. This includes 19 previously absent retained files and four installed variants. They are inspection evidence, not promoted as current release code. |
| Three apparently missing files were duplicates under other published paths. | The Mac GUI/mission launchers already exist under `ApplicationSources/Mac/PortalAI/Launchers`; the diagnostic BAT exists under the Windows `Launchers` directory. |
| Documentation index still called r45 current while the README advertised r51. | Corrected the index and distinguished the packaged r51 release from this later source patch. Historical release reports remain historical. |

## What was compared

The installed-code comparison covered `Agent`, `ControlCenter`, `Launchers`,
`Tools`, `Maintenance/Tests`, `Installer`, `Scientific`, `Workflows`,
`HomeAssistant`, and root code files with Python/PowerShell/shell/C/C#/JS/HTML/CSS
extensions. It excluded private state, caches, models, dependency/vendor trees,
maintenance backups/development/evaluations and nested source mirrors. Bundled
KiCad, FFmpeg, PrusaSlicer and SoX code/documentation was classified as third-party,
not missing original PortalAI code. Text comparisons allowed CRLF/LF equivalence.

Before this patch, 823 inspected D: files and 821 E: files matched their published
Windows source. The mission runner/supervisor matched byte-for-byte on both drives.
Two D: paths and three E: paths differed: retained Linux/Mac installer scripts and
`rename_portalai_root.ps1`. The four unique changed versions were preserved in the
supplementary source collection without replacing either installation's unrelated
files. Twenty other unique original source files were absent at matching paths;
one is the active portable Python wrapper and nineteen are retained source.

This is not a claim that every experimental file anywhere on either SSD should
ship, or that every third-party runtime has been independently reverse-engineered.
No user histories, accounts, credentials, model files or local AGENTS history were
uploaded. No deprecated C: application was updated.

## Remaining documentation limitations

[SOURCE-INVENTORY.json](SOURCE-INVENTORY.json) explicitly lists Python files
without a top-level module overview. In the Full Windows tree there are 130 such
files; in Academic Windows there are 123, including tests and older scripts.
Examples include `Agent/ai_tools.py`, `web_tools.py`, `service_manager.py`,
`science_tools.py` and several media bridges. Many have function comments, tests
or offline Help; absence of a module docstring alone does not prove that their
behavior is undocumented. The source map explains the subsystem boundaries, and
the generated inventory exposes their symbols and exact files. A complete API
specification for every function remains future documentation work.

The audit also makes the operational limits explicit: no arbitrary-effect
exactly-once guarantee, no unconditional survival of physical USB removal, no
autonomous resurrection of a dead host/supervisor, and no native Linux/macOS
hardware acceptance from Windows source tests. Ongoing schedules with
`max_runs=0` intentionally have no finite total occurrence count.

## Validation and installation

- All six Full/Academic Windows/Linux/Mac source variants passed **134 mission,
  persistence, schedule, review, account, context and priority tests each** on
  Windows with Python 3.12. See [validation records](MISSION-RECOVERY-VALIDATION.json).
- New tests cover failed result replacement, failure after checkpoint commit,
  corrupt checkpoints, persisted retry bounds, real Windows worker timeout/restart,
  an effectful process crash without duplicate execution, and Stop preventing relaunch.
- D: and E: were updated using the existing `portable_update.py` closed-account,
  edition, exact-baseline, verified-backup, readback and rollback workflow. Only
  two production modules, two test files and one guide changed. Their bundled
  Python and existing runtime/model installations were retained.
- Each SSD retains its own recovery copy under `Maintenance/Updates` and a
  self-contained source-update kit under `Utilities/Mission-Recovery-20261029`.
  Runtime use and update recovery do not require the temporary C: checkout.
- Both installed drives passed all 134 tests using their own bundled Python 3.12.14, plus six real-process persistence smoke checks each. The E suite initially had one timeout during concurrent testing; its isolated and complete serial reruns passed. The cause of that timing failure is not established.
- Portable-kit rollback was verified against a disposable five-file fixture; the real installation remained patched.
- The r51 download archives were **not rebuilt** by this source patch. Their
  version is deliberately not relabeled. A future full distribution build must
  include the new source; current r51 recipients can use the guarded source update.

## Apply the source patch to a matching Windows r51 installation

From a complete source checkout, use the target installation's bundled Python:

```powershell
& 'X:\PortalAI Windows\Runtime\BootstrapPython\python.exe' -B `
  '.\ApplicationSources\Windows\PortalAI\Installer\Windows\portable_update.py' `
  --source '.\ApplicationSources\Windows\PortalAI' `
  --target 'X:\PortalAI Windows' `
  --manifest '.\tools\mission-recovery-update-Windows.json'
```

This first invocation only reviews the plan. After normal Exit, append `--apply`
to apply it. The edition, baseline source hashes, stopped processes and sealed
account state must match; mismatches are reported instead of overwritten. The
patch retains the r51 version stamp and has its own explicit patch identifier.
The D:/E: portable kits include local Review/Apply/Recover commands and sources.

On the next normal launch, PortalAI imports the updated files. This audit did not
launch or replay any owner's missions, restart a live account session, or alter
repository visibility.
