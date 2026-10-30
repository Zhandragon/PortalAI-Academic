# Integration patch validation — 2026-10-29

Features 4–6 are implemented: schema-constrained generation, application API v1 with Python/TypeScript clients, and interactive versioned HTML/SVG/chart artifacts. Both Full Windows SSD installations were updated independently. The deprecated C: installation was excluded. Development checkouts do not form part of the runtime dependency graph.

## Results

| Check | Result |
| --- | --- |
| Installed regression suite, D: | 272 run: 271 passed, 1 skipped (host does not allow the test symlink). 37.382 seconds. |
| Installed regression suite, E: | 272 run: 271 passed, 1 skipped (same host symlink restriction). 40.461 seconds. |
| API boundary and SDKs | Actual loopback HTTP authentication/scopes/Host/Origin checks, token revocation, Python and TypeScript clients, durable same-key response replay, different-key uncertain-effect refusal, cancellation, job ownership, restart review, chat commit and chunked output identity. Included in the installed suite. |
| Artifact persistence | CAS revision conflicts, immutable history, restore, export protection, interrupted head publication, checksums and path rejection. Included in the installed suite. |
| Real encrypted profiles | Artifact content/history, token hashes and receipts survive seal/reopen and lazy hydration; stale login objects are rejected. Included in the installed suite. |
| Actual CPU model, both SSDs | Bundled Qwen3VL-2B-Instruct Q4_K_M obeyed a nonce/integer schema despite a contradictory prose prompt, and emitted a valid Observe completion proposal. No owner mission/action executed. |
| Actual portable Chromium, both SSDs | Inline counter and chart toggles worked. Parent DOM, local storage, popup, network and local-file probes were refused. Browser OS sandbox enabled. |
| Owned preview worker, both SSDs | Bundled Python/browser startup succeeded; shared Stop cleanup terminated the owned worker. |
| Native UI, both SSDs | Seven tabs rendered in light, dark and 560-pixel narrow layouts; no Tk callback errors. Save/revise/restore/export and API start/token/stop controls exercised against synthetic state. |
| Real persistence processes, both SSDs | Six checks passed: exclusive supervisor dispatch, durable scheduled wait, autonomous resume, uncertain-effect no replay, descendant cleanup on controller crash, Stop before late planning effects. |
| Source/kit integrity | Guarded updates verified, installed hashes match manifests, complete kits have checksums and independent rollback journals. Full and Academic changes preserve their platform/edition differences. |

New tests are `Maintenance/Tests/test_integration.py` and `test_integration_profiles.py`; actual runtime acceptance is `Tools/smoke_integration.py`. Full module lists and logs are in each SSD's `Maintenance/Validation/Integration-20261029`. Acceptance ran from installed source with that SSD's bundled Python, Node, model and browser; no host runtime or other SSD is required by the application.

## Limits and failures retained

The legacy `Tools/system_test.py --skip-science-functional` was attempted on both SSDs but could not save its account-private report while logged out (`ProfileLocked`). It is not counted as passed and account guards were not bypassed. The separate feature tests use explicitly synthetic fixtures.

An early source-only regression run lacked the installed bundled-runtime path and failed four shell-prefix classification assertions. The complete installed suites subsequently passed; no production permission rule was relaxed. The first test-only preview adapter lacked its fixture's Python lookup; the test adapter was corrected to borrow the actual bundled interpreter. The shipped worker still resolves its own installation normally.

Windows checks do not prove native Linux/macOS execution, physical USB-removal durability, every possible browser exploit, arbitrary schemas, or end-to-end inference for every unrelated media model. Schema validation establishes output structure, not truth. Existing private profiles and owner missions were not resumed or modified by acceptance tests. Historical r51 download archives were not rebuilt; the individually browsable source and offline SSD kits carry this patch.

## Python duplication audit — no consolidation

The read-only inventory found 14 interpreter/launcher candidates on each SSD and distinct cp310/cp311/cp312/native GPU requirements. Four old uv launchers fail; current Qwen and MuseTalk bridges bypass their obsolete launchers while using their package layers. Optional OpenWebUI launch paths still need a separate portability repair.

SHA-256 comparison of the two Qwen package trees found 4,836,396,718 identical bytes on D: and 4,837,163,893 on E: (about 4.50 GiB each), with differing and unique files retained. This is a consolidation candidate, not a safe deletion list. No Python, NumPy, package or runtime selector was merged or removed. See [the dependency map and assessment](PYTHON-DISTRIBUTION-AUDIT-20261029.md).
