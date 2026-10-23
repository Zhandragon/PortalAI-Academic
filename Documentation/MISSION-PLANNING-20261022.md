# Scheduled mission planning and memory progress

PortalAI mission planning progress — 2026-10-22 r5

The planner chooses one action at a time. complete(text) reports completion;
it does not save memory, replace a value, or perform any other requested work.
Memory lookup outcomes now distinguish a completed empty search from a failed
request. Parsed results and the last completed step remain visible during
context compaction. Scheduled plans receive the current occurrence number and
the count of previous completed runs, read from the actual schedule checkpoint.
Results now shows memory-write requests and recorded outcomes alongside the
model-reported completion. A summary claiming success is distinct from evidence
of executed work. Reviewed/skipped requests retain their recorded outcome and
are not labeled as verified writes.

Mission planning requests bounded model reasoning (up to 512 tokens). With a
context of at least 4096 tokens, 1280 output tokens are reserved, including the
reasoning allowance; smaller contexts retain a 768-token output cap. The full
input, reserved output and headroom remain budgeted. Live activity shows actual
reasoning as it arrives. Reasoning is uncommitted output, never an action or
execution evidence. Only a complete final JSON response can execute.

Malformed argument shapes and an immediately repeated completed action receive
one corrective planning attempt before any pending action is recorded. These
rejected proposals consume no mission actions. A failed correction pauses for
review. The existing repeated-action guard and uncertain-effect review remain.
At most two model requests are permitted for one action decision: the initial
proposal and one invalid/duplicate correction. A valid completion is accepted
as a model decision, not a formal proof of an arbitrary goal. wait pauses only
the current occurrence; complete ends it so the scheduler can start a later
occurrence. Wait still permits deliberate polling. Stop, login changes, foreground chat and
schedule disarming cancel planning without replaying work.

Validation includes one complete Qwen3-4B-Q4 CPU test in a disposable authenticated
account: five actions per occurrence, two occurrences, a one-minute interval,
and supervisor restart between them. Success requires the exact requested
FIRST_PASS value, then the exact replacement SECOND_PASS value under the same
key. A completion label alone is not sufficient. The validation summary gives
the tested cases and limitations. Earlier experimental revisions failed this
semantic check and were not published.

An additional Full-mode trial recorded both correct memory writes, then hit a
Windows PermissionError while the harness read mission.json. It was stopped
and sealed, and is not counted as a passing test. Its model handoff check was
not reached. The completed test used observe mode and also verified Stop
during real reasoning. Further model experiments ended here.

Qwen3-1.7B-Q8 did NOT reliably complete this conditional memory test, even with
explicit results, scheduled occurrence state and bounded correction.
Sampling changes, shorter prompts and native function calls did not
establish a reliable 1.7B fix. It sometimes chose the wrong write or completed
without writing. The engine and scheduler can be working while a model makes
these mistakes. The investigation report retains the failed experiments.

For conditional or recurring work, install/select the standard 4B model or a
more capable model that fits the machine. The 4B model passed only the cases
recorded here; no arbitrary-goal or unattended-operation guarantee is made.
Personal model selection is preserved and never silently upgraded. Review
actual results. Existing needs-review missions remain paused. Add
review instructions and explicitly Enable only after inspecting their outcomes.
The owner account's missions were not replayed. Physical Aoostar, Linux and
macOS execution must be checked on those machines. Normal Exit/relaunch loads
the updated application source. Clean installers are for new installations.

Validation evidence:

```json
{
  "passed": true,
  "edition": "Full",
  "platform": "Windows",
  "models": [
    "qwen4-q4"
  ],
  "backend": "CPU",
  "context_tokens": 8192,
  "per_run_action_budget": 5,
  "interval_seconds": 60,
  "scheduled_occurrences_per_case": 2,
  "cases": [
    {
      "case": "acceptance4b-observe-final",
      "model": "qwen4-q4",
      "mode": "observe",
      "objective_form": "original next-run wording",
      "objective": "Look up the memory key schedule_probe. If it does not exist, save FIRST_PASS_BC5B78, then complete the run. On the next scheduled run, read that value, replace it with SECOND_PASS_BC5B78, then complete.",
      "actions": [
        [
          {
            "action": "recall",
            "query": "schedule_probe"
          },
          {
            "action": "remember",
            "key": "schedule_probe",
            "text": "FIRST_PASS_BC5B78"
          },
          {
            "action": "complete",
            "text": "schedule_probe memory key initialized with FIRST_PASS_BC5B78."
          }
        ],
        [
          {
            "action": "recall",
            "query": "schedule_probe"
          },
          {
            "action": "remember",
            "key": "schedule_probe",
            "text": "SECOND_PASS_BC5B78"
          },
          {
            "action": "complete",
            "text": "Objective fulfilled for occurrence 2: saved 'schedule_probe' as 'SECOND_PASS_BC5B78' and completed the run."
          }
        ]
      ],
      "exact_memory_writes_verified": true,
      "controller_restarted": true,
      "stop_during_reasoning": true,
      "live_reasoning_observed": true,
      "tested_source_matches": true,
      "sealed": true,
      "fixture_listener_stopped": true
    }
  ],
  "source": [
    {
      "path": "Agent/mission_runner.py",
      "sha256": "0481a20689e054f0c566dab807c058452a07ade61f0a1702ff5cb9deb0a283af"
    },
    {
      "path": "Agent/mission_context.py",
      "sha256": "832a4baa4d6a926ee02c6da8603c2df32930cafb305742ee3caa7868548f2b69"
    },
    {
      "path": "Agent/chat_priority.py",
      "sha256": "45a28053799131c752a1f9493d6154854ca25c80704b6f797d13faec222745ec"
    }
  ],
  "limits": "One completed two-occurrence test in a disposable Full-edition Windows account, observe mode. An additional Full-mode trial recorded both correct writes but was interrupted by a Windows PermissionError while the harness read mission.json; it is not a passing acceptance case, and its owned-model handoff check was not reached. Academic shared logic and edition policy have unit coverage, not a live Academic model run. No owner mission replay, physical Aoostar, Linux or macOS acceptance. Model completion decisions are fallible; arbitrary objectives are not guaranteed. Qwen3-1.7B-Q8 did not reliably complete the conditional memory probe; see investigation.json. No owner model preference was changed."
}
```
