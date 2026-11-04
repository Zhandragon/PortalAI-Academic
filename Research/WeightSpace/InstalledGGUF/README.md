# Installed-GGUF weight-space campaign

This is the current natural-failure campaign, separate from the older synthetic
pilot in the parent directory. It uses only PortalAI's installed standard and
abliterated 1.7B Q8, 4B Q4 and 27B Q4 files. The deployed original files remain
unchanged. See [RESULTS.json](RESULTS.json) for dated progress and honest limits.
The [selected recipes and edit receipts](Profiles/) are individually readable
JSON; [optional profile downloads](OPTIONAL-PROFILES.md) avoid repeating the
experiment when a user explicitly wants to try a recorded tradeoff.

## Recorded outcomes

| Installed model | Original | Edited | Random control | Decision |
| --- | ---: | ---: | ---: | --- |
| 1.7-standard | 18/28 | 18/28 | 19/28 | Edit rejected; original retained |
| 1.7-abliterated | 20/28 | 18/28 | 20/28 | Edit rejected; original retained |
| 4-standard | 22/30 | 21/30 | 23/30 | Edit rejected; original retained |
| 4-abliterated | 18/24 | 13/24 | 20/24 | Edit rejected; original retained |
| 27-standard | 53/56 discovery only | Not evaluated | Not evaluated | No supported outcome contrast; no edit evaluated |
| 27-abliterated | 24/27 discovery only | Not evaluated | Not evaluated | In progress |

Counts are correct answers on each model's frozen discovery cases. The case sets differ, so these rows do not rank the models against one another.

**The campaign is not yet complete.** No original model has been replaced. Discovery results alone cannot establish a general improvement.

[Completion diagnostics](COMPLETION-DIAGNOSTICS.json) separately report token
limits, correct answers with a natural stop, output lengths and repetitive
tails. They are post-hoc descriptions of completed comparisons, not new
selection rules. Repetition is a heuristic and cannot detect every reasoning
loop. The read-only analyzer is published alongside these results.

**27B sampling correction (2026-11-04):** the pinned native API clamps a
negative penalty history to zero. Earlier 27B discovery therefore used no
presence penalty despite requesting 1.5. Those records are archived unchanged
and superseded for protocol conclusions. See [SAMPLER-CORRECTION.json](SAMPLER-CORRECTION.json)
for exact counts, source evidence and the verified repair. Corrected 27B runs
restart from the frozen cases with a positive generated-token history. The 1.7B and 4B comparisons
request zero penalty and are unaffected. No original models were replaced.

## Method and boundaries

1. Collect natural completions from 24 frozen practice problems, at the pinned
   32,768-token reply budget. If fewer than four successes or failures occur,
   gather a further 32 preselected discovery problems. No synthetic bad reasoning.
   Here success means a correct answer with a natural stop; failure means an
   incorrect answer. Correct answers extracted from limit-hit replies are
   reported separately and do not enter either localization group. Therefore
   a lack of incorrect answers does not establish an absence of inefficient
   or unfinished reasoning, and this accuracy-contrast hypothesis does not
   directly target every kind of loop.
2. Replay actual prompt/completion tokens through the native quantized graph.
   Compare successful/unsuccessful activation means and rank internal MLP sites.
   These groups are not matched by topic or difficulty: localization is a
   hypothesis generator, not proof that a direction specifically causes loops.
3. Select sparse 64-column MLP down-projection subtraction. Compare three sites,
   zero-dose equivalence, five doses and norm-matched orthogonal random controls.
   Diagnostic reference loss is measured on worked solutions where available,
   otherwise on answer-only text; it is not task accuracy.
4. Serialize the selected edit directly into a separate GGUF, requantizing only
   affected blocks. Compare real original, edited and random-control generations
   on selected natural cases plus frozen coding, tool and instruction checks.
   Tool calls are inspected and never executed. Original files are never edited.
   CPU preflight ranks the existing diagnostic-loss grid and admits only edits
   whose intended and actual quantized matrix change stay within the editor's
   unchanged 15% norm bound, for both candidate and random control. It does not
   use generated candidate answers or final benchmark results to select a dose.
5. A candidate must improve over both original and random control without a
   discovery-domain regression to reach 1,152 unique, unseen paired confirmation
   problems. Recipe and data hashes freeze before opening confirmation data.
6. Only positive independent evidence can reach separate broad final benchmarks
   and the latency gate. No new model is promoted on a missing or failed check.

The [protocol](protocol.json) records limits and acceptance criteria. The
[code actually used by the editor](../../../ApplicationSources/Windows/PortalAI/Tools/WeightSpace/)
contains native activation capture, direct quantized subtraction, accounting,
grading, storage admission and owned workers. This campaign selects one
hypothesis per model; it does not exhaust the permitted search budget.
`research_grading.py` records a model program that exceeds its bounded code
execution time as incorrect. It preserves infrastructure errors and other
grader failures for review. Existing successfully graded records are unchanged.

The reference is [Takehi et al.](https://rikiyat.github.io/blog/weight-space-programming/)
and [their pinned experiment source](https://github.com/RikiyaT/lm_understand-logs/tree/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math).
This run uses Codex as editor and actual quantized llama.cpp execution, rather
than claiming identical Astra/BF16/vLLM execution or copying 0.8B edit vectors.
It does not download unrelated model weights. Original unreleased seeds cannot
be reproduced; stable per-item seeds are explicit in the native source.

## Reproduction

Use the corrected Windows utility with `native-generated-history-v2` sampling
(r68 source/release), with its existing portable runtime. r67 and earlier native
sampling code must not be used for the nonzero-presence-penalty protocol. Copy this
folder to `PortalAI Windows/Maintenance/Research/Takehi-PortalAI-20261103` in a
fresh workspace; never overlay a live experiment. The scripts deliberately
derive the installed portable root from that location. Use BootstrapPython.
The native probe currently requires the pinned Windows x64 NVIDIA runtime;
this is not evidence of Radeon or other-platform benchmark execution.

`prepare_practice.py --download` fetches only the three checksum-pinned public
practice files. Alternatively use `--source-directory` with those existing
files. Both paths reconstruct exactly the recorded practice bytes. Frozen
splits and duplicate exclusions ship here; final benchmark questions are not
inputs to direction, site or dose selection. `practice-sources.json` records
upstream identity, sizes, checksums and canonical serialization.

For each model ID in protocol.json, run `discovery.py --model ID`, then
`causal_screen.py --model ID`, then `generation_screen.py --model ID`, using
`Tools/WeightSpace/run_owned.py` with absolute script/log paths. The start gate,
shared GPU lease and Windows job are mandatory; the worker will not run by
direct invocation. Review each stage before starting conditional confirmation.
Use `confirm_candidate.py --model ID` only after discovery eligibility.

`run_remaining.py` and `resume_generation.py` are continuation tools for the
recorded campaign. They require its saved case hashes/checkpoint and must not
be used to invent missing evidence in a fresh run. The resume path skips
completed cases, starts an interrupted inference from its original seed,
records another accounted pass, and refuses automatic removal of a user pause.
The 4B standard model's first dose was rejected during serialization because
it exceeded the norm bound. `prepare_feasible_resume.py` retains its rejected
partial and original recipe, verifies every completed baseline case, and
selects the best already-scored feasible dose. The generation script's
`--resume-feasibility` mode verifies that checkpoint and evaluates only the new edit
and control. The initial interruption remains in the experiment ledger.

## Reversible profiles and storage

The evaluated candidate can be exported to an exact compressed `.wsedit`
profile. Keep the original; prepare a derived copy only when wanted. Choose
the profile or Original weights under Settings > Chat models. A different
model/variant retains its own original. Switching requires a model reload and
never replays a completed or uncertain tool effect.

The first profile is about 25 MB; the prepared GGUF still occupies the full
model size. At most two prepared copies are retained, with replacement
verification before eviction and an 80 GiB reserve even during staging.
Current profiles are experimental, not automatic upgrades. A rescued task
does not justify calling an edit broadly more intelligent.

## Separate final evaluation

The pinned manifest lists MATH-500, GSM8K, AMC23, Minerva, OlympiadBench,
MMLU-Pro, IFEval and an explicitly restricted MBPP adaptation. GPQA-Diamond
is gated and has not been downloaded; no complete Takehi benchmark claim is
made. Final execution and additional task fixtures are conditional on a
candidate qualifying; they are not run for rejected candidates. Do not infer final benchmark scores from downloaded data
or from discovery. Full raw results are retained on the research SSD; this
folder publishes code, provenance and compact summaries without full weights.
