# Mission supervision, recovery and durable state

This is the implementation contract for the 2026-10-29 mission recovery source
patch. The r51 download archives predate this patch unless their release notes
explicitly say otherwise. Source publication and installed-file verification are
recorded separately in [the audit](SOURCE-AUDIT-20261029.md).

## Direct source links

These are ordinary, individually committed files; no installer extraction is
needed. Full repository links require approved GitHub access. The Academic
repository exposes its corresponding implementation publicly.

| Component | Windows | Linux | Mac |
| --- | --- | --- | --- |
| Python worker and checkpoint state machine | [mission_runner.py](../ApplicationSources/Windows/PortalAI/Agent/mission_runner.py) | [source](../ApplicationSources/Linux/PortalAI/Agent/mission_runner.py) | [source](../ApplicationSources/Mac/PortalAI/Agent/mission_runner.py) |
| Supervisor, process ownership and retries | [mission_supervisor.py](../ApplicationSources/Windows/PortalAI/Agent/mission_supervisor.py) | [source](../ApplicationSources/Linux/PortalAI/Agent/mission_supervisor.py) | [source](../ApplicationSources/Mac/PortalAI/Agent/mission_supervisor.py) |
| Opt-in recovery decisions | [mission_recovery.py](../ApplicationSources/Windows/PortalAI/Agent/mission_recovery.py) | [source](../ApplicationSources/Linux/PortalAI/Agent/mission_recovery.py) | [source](../ApplicationSources/Mac/PortalAI/Agent/mission_recovery.py) |
| Scheduled occurrences and authorization | [mission_schedule.py](../ApplicationSources/Windows/PortalAI/Agent/mission_schedule.py) | [source](../ApplicationSources/Linux/PortalAI/Agent/mission_schedule.py) | [source](../ApplicationSources/Mac/PortalAI/Agent/mission_schedule.py) |

## Answers to the five verification questions

| Question | Actual behavior | Implementation |
| --- | --- | --- |
| What detects a stalled mission? | The supervisor enforces **480 seconds of total monotonic elapsed worker time**, plus a 2 MiB error-log cap. This is a hard worker lifetime, including startup/planning/execution; output or heartbeat activity does not reset it. | `Supervisor.tick`, `WORKER_TIMEOUT_SECONDS`, `WORKER_LOG_LIMIT_BYTES` |
| Does recovery restart Python? | Yes. The supervisor closes the owned worker job, waits for termination, reconciles the on-disk mission, and later launches a **new Python process** for one step. A worker's caught planning failure instead records a delay; the supervisor subsequently launches the next worker. | `WorkerJob`, `finish_worker`, `reconcile`, `tick`; `Missions.run` |
| Do checkpoints survive crashes and drive removal? | A committed checkpoint is persistent disk state. Writes flush and fsync a temporary file, then replace the destination. The previous JSON is retained as review evidence. A removed, damaged or unflushed drive cannot be guaranteed to preserve the latest write; execution cannot continue without the storage. Reconnect, reopen and authenticate as needed. Corrupt/missing checkpoints are **never silently restored from an older copy**. | `Missions.save/load`, `runtime_policy.atomic_json`, `profile_paths`, `profile_workspace` |
| Are retries bounded and effects protected? | Worker failures, planner failures and opt-in recovery have limits below. `pending_action` is saved **before** dispatch. Uncertain side effects require review. Dedicated account operations also use durable operation journals. This is replay protection, **not a universal exactly-once guarantee** for arbitrary shell commands or remote systems. | `Missions.run`, `Supervisor.reconcile`, `mission_recovery.recover`, `mission_accounts.Accounts.call` |
| Can a stalled mission resume autonomously? | Yes, an armed mission interrupted before an uncertain effect is retried while its authorized supervisor remains running. An enabled schedule with autonomous recovery can replan classified read-only failures. Stop/Exit, locked accounts, revoked policies, exhausted budgets, damaged state and uncertain effects can require user action. No OS startup service is installed; a dead supervisor/host is not guaranteed to restart itself. | `ensure_running`, `selection`, `tick`, `Schedules.tick`, `recover` |

The supervisor writes its own `supervisor-status.json` heartbeat at least every
five seconds while ticking. It describes controller liveness; it is **not a
worker heartbeat watchdog**. `activity.json` reports worker progress and is not
an execution checkpoint. Tool-output inactivity does not trigger the mission
worker timeout. Timeout and oversized-log cancellation now record distinct
failure reasons instead of only “Worker exited”.

## Three different recovery mechanisms

1. **Mission process supervision:** owns the Python worker process tree, observes
   exit, and enforces the elapsed-time/log limits above.
2. **Scheduled mission replanning:** `mission_recovery.py` is opt-in and off by
   default. Only a schedule's current occurrence, with valid enabled policy and
   Stop epochs, can recover. It records failed evidence separately from successful
   history and asks the planner to change strategy. It will not clear uncertain
   shell, email, payment or other effectful actions.
3. **NativeChat progress assistance:** [coding_stall.py](../ApplicationSources/Windows/PortalAI/ControlCenter/coding_stall.py)
   and [task_progress.py](../ApplicationSources/Windows/PortalAI/ControlCenter/task_progress.py)
   act between completed model/tool calls. The r51 default interval is 300 seconds
   with eight qualifying interactions and bounded intervention phases. They guide
   later model turns, do not restart Python workers, and cannot interrupt an
   ongoing reasoning response or tool job. See [the r51 specification](Task_Progress_r51.txt).

## Retry limits

| Failure path | Limit and delay |
| --- | --- |
| Worker exit/timeout without a pending action | Persisted `worker_failures`; retries after failures 1–3, then `needs_review` on failure 4. Delays: 20, 40, 80 seconds. This count is not reset merely by constructing a new supervisor. |
| Caught planning errors without schedule recovery | Persisted `planning_failures`; five retries, then review on failure 6. Delays: 15, 30, 60, 120, 240 seconds. Context/loop errors can require review immediately. Successful planning resets this planning-error count. |
| Opt-in schedule recovery | Each failed decision consumes one action from that occurrence's `max_steps` (1–100), with exponential delay capped at 300 seconds. Failure evidence is not a successful result. |
| Recurring schedule | `max_runs` bounds occurrences when nonzero. Zero intentionally means ongoing recurrence; it is **not a finite total retry budget** across the entire schedule. Each occurrence still has its own bounded action budget. |

An enabled recovery schedule may recover a `needs_review` planning/read-only
failure through `Schedules.tick`; therefore the four-worker limit is not an
absolute limit across such schedule replans. The occurrence action budget remains
the bound. Stop flags, schedule/remote epochs, mode permissions, explicit agent
pauses and child-wait states remain authoritative.

## Checkpoint and effect ordering

```text
plan -> save pending_action -> execute -> save result + clear pending_action
                                      |
                                      +-- crash / uncertain result -> needs_review
```

The mission folder is `Data/Missions/<id>` in the captured account workspace
(`Private/Users/<id>/Workspace/...` for account-backed installations). It contains
the authoritative `mission.json`, the previous evidence copy, run policy, Stop
marker and progress/error files. Account vault and hydration logic preserve these
records through normal sealing/restoration; the profile must be available to run.

The new result-save fix reloads **the authoritative checkpoint** when saving a
returned result raises an exception. If it still contains `pending_action`, the
action remains unresolved and normal Resume requires an explicit skip/retry
decision. If the result committed and a subsequent index write failed, the saved
result and completion status remain intact. If the checkpoint is unreadable, the
exception propagates without overwriting evidence with in-memory state.

Dedicated account operations derive a journal identity from mission, step,
profile, operation and parameters. A confirmed identical operation returns its
stored receipt; a pending journal blocks automatic dispatch. This does not dedupe
semantically equivalent operations with different identities or make an arbitrary
external service transactional. Other effects rely on pending-action quarantine.
Repeated-action detection is a planning guard, not a semantic idempotency system.

`atomic_json` currently fsyncs file bytes before replacement; it does not provide
a cross-platform directory-fsync/device-power-loss transaction. Abrupt USB removal,
controller failure and filesystem corruption remain outside an unconditional
durability guarantee. Keep normal Exit/safe-eject procedures. No backup on a
disconnected drive makes that drive available to a running process.

## Reproduce the tests

Use the installation's bundled Python 3.12 from its root (or prepare the pinned
account dependencies for a source checkout). All tests use disposable missions,
synthetic planners and simulated accounts; they do not run owner missions.

```powershell
.\Runtime\BootstrapPython\python.exe -B -m unittest discover -s Maintenance\Tests -p test_mission_crash_recovery.py -v
.\Runtime\BootstrapPython\python.exe -B -m unittest discover -s Maintenance\Tests -p test_persistence_supervisor.py -v
.\Runtime\BootstrapPython\python.exe -B -m unittest discover -s Maintenance\Tests -p test_mission_autonomous_recovery.py -v
```

[The new regression suite](../ApplicationSources/Windows/PortalAI/Maintenance/Tests/test_mission_crash_recovery.py)
injects failed result publication, post-commit indexing failure and corrupt storage;
checks the persisted worker-failure bound; and uses real Windows Job Objects and
child processes to prove timeout restart/completion, no replay after an effectful
crash, and Stop preventing relaunch. It accelerates timeout/backoff clocks, not
the recovery state machine. Linux/Mac source checks executed on Windows are not
native Linux/Mac process-ownership acceptance or real USB-removal tests.

The [follow-up bug review](BUG-REVIEW-20261029.md) extends bounded worker recovery to launch failures and fixes schedule setup backoff after checkpoint creation.
