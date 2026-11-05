# CPU coding preparation and reviewed recovery

This is preparation for a conditional final benchmark, not model performance
evidence. Independent confirmation remains in progress. No original model or
production selection has changed.

The adapter parses the pinned sanitized MBPP test syntax into the existing
portable pure-function checker. Ten CPU tests passed, including rejected
nonliteral calls, unsupported value types, name collisions and input mutation.
All 257 test rows were reviewed. Exactly 129 reference programs pass the owned
512 MiB / five-second checker. The other 128 rows are excluded with individual
reasons in portable-subset.json. This is explicitly a restricted subset, not a
full MBPP score. The selected cases must still be included in a disjointness-
checked, immutable final plan with seeds, repetitions, prompts and other domains.
No final model answers have been generated or used to select these cases.

The original locations of mbpp_adapter.py, test_mbpp_adapter.py and
prepare_mbpp_subset.py are Maintenance/Research/Takehi-PortalAI-20261103.
The subset lives under that directory's final-benchmarks/MBPP. This source
depends on the existing portable evaluator and is published for inspection.

The first confirmation worker exited on 2026-11-05 at 00:59:09 UTC with a Windows
native access violation (0xC0000005 in python312.dll). The cause is undetermined.
All 188 committed cases, request hashes, JSON mirrors, frozen inputs and both
model hashes passed review. Recovery copies were verified on D and E before a
single reviewed continuation of the unchanged worker. Completed cases were
preserved; the interrupted pass stays accounted. The resumed worker completed
new cases. Another error stops for review; no automatic error-retry loop was
added. CRASH-REVIEW.json and the review source preserve that evidence. This does
not establish that the underlying crash cause was fixed.
