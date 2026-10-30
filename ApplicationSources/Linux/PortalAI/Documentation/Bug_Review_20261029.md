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
