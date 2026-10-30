# Mission setup and worker launch fixes — 2026-10-29

The follow-up bug review reproduced and fixed three failures:

1. **Schedule setup retried too soon.** If mission creation succeeded but publishing
   its run policy failed, the scheduler ignored its saved delay and reset its failure
   counter before the next publication attempt. It now preserves the counter until
   policy publication succeeds and waits 30, 60, 120, 240, then 300 seconds between
   setup attempts. It reuses the same occurrence ID. Setup retries remain unbounded
   in count while the schedule stays enabled; their delay is capped at 300 seconds.
   Stop, pending effects, and completed runs are inspected during the delay.
2. **Worker launch failure stopped supervision and leaked the log handle.** Failure
   before a process was returned escaped the loop without closing worker-error.log.
   Launch/setup exceptions now close owned resources and use the existing persisted
   worker-failure budget: 20/40/80-second waits, then review at failure four. The
   start gate remains closed until OS process ownership succeeds. KeyboardInterrupt
   and other BaseException exits still clean up and propagate without a retry.

3. **Recovery storage errors were swallowed as lock contention.** Once a mission
   lock is acquired, checkpoint read/write errors now propagate and stop recovery.
   The supervisor cannot keep launching workers without saving its retry count.

Eight regression tests in Maintenance/Tests/test_mission_setup_recovery.py cover
the delays, restart persistence, same occurrence, Stop/effect/completion handling,
bounded launch failures, interruption cleanup, a real Windows worker recovering
after failed spawn, and termination when process containment fails.

No action is automatically replayed when its external outcome is uncertain.
The 480-second worker lifetime, planning limits, permission modes and account/Stop
fences are unchanged. Offline fault injection does not certify every model, GPU,
network provider, physical drive removal, or native Linux/macOS path.

The D: and E: Full r51 installations receive this source patch independently.
The old C: installation is excluded. Each SSD keeps its own checksum-verified
backup and Utilities/Bug-Review-20261029 kit with source, bundled-Python launchers,
guarded apply and rollback. No C: checkout, host Python, GitHub login or internet is
needed by the installed fix or kit. Move the kit and sibling PortalAI Windows
folder together when changing drive letters. Close PortalAI normally before
applying/restoring. Review.cmd is read-only; newer differing source is refused.

The release version stays r51: the downloadable r51 installer archives were not
rebuilt. Normal application launch loads the updated source. Validation evidence
is under Maintenance/Validation/BugReview-20261029 on each SSD and in the repository
Documentation/BUG-REVIEW-VALIDATION-20261029.json.

## Individually accessible source

- [Scheduler](../ApplicationSources/Windows/PortalAI/Agent/mission_schedule.py)
- [Supervisor](../ApplicationSources/Windows/PortalAI/Agent/mission_supervisor.py)
- [Regression tests](../ApplicationSources/Windows/PortalAI/Maintenance/Tests/test_mission_setup_recovery.py)
- [Guarded Windows patch manifest](../tools/bug-review-update-Windows.json)
- [Validation record](BUG-REVIEW-VALIDATION-20261029.json)

Equivalent method changes are included in the Linux and Mac source trees, retaining
edition/platform-specific process launch behavior. Those sources were exercised
on Windows; this is not native Linux/macOS acceptance. Full remains private;
the corresponding Academic source remains public.

This review follows [the earlier source/recovery audit](SOURCE-AUDIT-20261029.md).
The earlier mission-recovery-update-Windows.json manifest is historical: use it
with the matching audit commit, not newer main source. Existing SSD recovery kits
retain their complete matching payloads. This new patch expects the earlier
mission-recovery patch to have been installed.

## Verified results

Both D: and E: ran **294 tests: 293 passed, one Windows symlink-privilege skip**,
using their own Python 3.12.14. Syntax/config scans passed for **902 selected owned
files on D: and 900 on E:**. Six real-process persistence smoke checks passed per drive.
All six Full/Academic platform source variants passed 58 focused tests each on
Windows. The final rollback helper restored all four changed files in a disposable
fixture, with live installations unchanged by that fixture.

The broader checks cover mission recovery/scheduling, account permissions, Stop,
profile shutdown, encrypted persistence/hydration, portable updates and storage
admission. No live model/GPU/provider work, native Linux/macOS acceptance or physical
drive-removal test was performed. The live-model smoke_schedules.py was not run;
the current installations were closed and this review used synthetic fixtures.
