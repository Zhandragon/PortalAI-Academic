# Weight-space experiment: reasoning, coding, math and tools

## Current quantized campaign and reversible profiles (r65)

**In progress; no new production weights accepted.** The r64 campaign uses only PortalAI's six actual installed GGUFs, natural practice failures, internal activation measurements, causal site/dose controls, directly serialized quantized subtraction, and independent confirmation before any deployment. The older pilot results below are historical and must not be read as results of this new campaign. Unrelated reference/BF16 downloads from the abandoned detour were removed; they are not required by the utility.

The [portable editing utility and exact source map](../../Documentation/WEIGHT-SPACE-r64.md) are shipped independently of whether an experimental model wins. It opens from PortalAI's Utilities panel and never silently replaces production weights. The current campaign is a native quantized adaptation, not a bit-identical reproduction of the authors' BF16/Astra/vLLM environment. Do not infer overall intelligence gains from preliminary rescued cases.

The current [campaign source, protocol, data pins and results](InstalledGGUF/README.md) are individually available. The [r65 reversible-profile guide](../../Documentation/WEIGHT-PROFILES-r65.md) explains prepare/select/revert, storage costs and experimental status.

## Historical pilot results


**Status: native weight-edit experiments, with no production edit accepted.**
All six installed standard/abliterated variants completed their native selection
baselines and causal calibration. Sparse experimental adapters were actually
loaded and evaluated; original GGUF files and the production model selection
remain unchanged. No broad intelligence gain has been established. The user
freed VRAM and GPU work resumed; the former game-session pause is no longer active.

Native strict passes were **9/12 standard 1.7B, 10/12 abliterated 1.7B,
10/12 standard 4B, 8/12 abliterated 4B, and 12/12 for each 27B variant**.
These are tiny selection diagnostics,
not general model rankings. Review separates correct mathematics with formatting
errors from actual coding and tool-selection failures. One standard 4B coding
response exhausted its 3,072-token allowance; the advisory repetition detector
flagged none. Three subsequent 6,144-token follow-ups completed that coding case
correctly in about 17–22 seconds; the original cutoff does not establish
unavoidable nontermination. Neither a cutoff nor a negative detector proves
whether a loop exists.
See [native results and reviewed limitations](NATIVE-PILOT-RESULTS.json) and
[actual edit evaluations and decisions](NATIVE-EDIT-RESULTS.json).

The calibration used four hand-authored productive/repetitive continuation
pairs, three separate layers per model, candidate and norm-matched random edits,
and doses 0, 0.5, 1 and 2: **1,152 adapter/continuation evaluations**. Zero-dose
equivalence passed for all six models. Only the two 1.7B variants passed the
frozen calibration gates; each then received 12 held-out tasks under unchanged,
candidate and random-control conditions. No edits passed production acceptance.
The synthetic direction is a calibration probe, not a proven natural looping
mechanism. Viewed pilot holdouts must not become tuning data for later claims.

Both 1.7B candidates scored **11/12**, equal to their respective baselines, with
one rescued case and one regression each. The standard edit broke bracket-type
nesting; the abliterated edit omitted the numeric final answer despite computing
it correctly. The random controls scored 10/12 and 11/12, respectively. These
tradeoffs do not justify replacing either installed model. Fourteen offline
checks passed independently on each drive, and E's own native runtime passed
the capture-on/off numerical smoke check without any logit difference.

A valid 12-case direct Torch pilot on the standard 1.7B weights completed:
**9 strict passes, no observed repetition loops and no cutoffs**. The three
failures were answer formatting despite a correct mathematical value, mutation
of an input list despite a coding constraint, and choosing a known default
avatar instead of the identified profile. These are selection diagnostics,
not general accuracy scores, and they do not justify a loop-suppression edit.
See [the bounded results and limitations](PILOT-RESULTS.json).

This adapts the diagnostic method from [Takehi et al., weight-space programming](https://rikiyat.github.io/blog/weight-space-programming/)
and the [released experiment notes](https://github.com/RikiyaT/lm_understand-logs/tree/main/exp8_math).
Their reported intervention used a Qwen3.5 **0.8B** model. The installed Qwen3
1.7B/4B and Qwen3.8 27B models require independent analysis; neither the selected
layers nor their edit vectors can be copied across models.

## Contents and limits

- `benchmark.py`: sequential, account-free native inference on six installed
  standard/abliterated models. Separate, frozen 12-case selection and 12-case
  held-out diagnostic sets cover math, pure-function coding, structured tool
  selection, and reasoning. They are a pilot, far too small to establish broad
  improvements. Tool calls are inspected, **never executed**. Model hashes,
  sampling, complete outputs, latency, finish reasons and repetition metrics are
  recorded. Native tests use the shared GPU lease and owned Windows jobs.
- `code_check.py`: restricted Python function grading in a child process with a
  four-second deadline and 256 MiB job limit. No imports, host I/O, private
  attributes or dynamic evaluation. This deliberately restricted evaluator is
  not a general OS sandbox or a full software-engineering benchmark. Unsupported
  programs are reported explicitly; inspection is needed before treating those
  failures as model reasoning errors.
- `inventory.py`: memory-mapped GGUF metadata/tensor inventory. The small models
  use `qwen3`; the 27B models use `qwen35`. The abliterated 27B file reports an
  additional block, so blindly reusing layer numbers is especially inappropriate.
- `capture_qwen3.py`: a streaming GGUF-to-BF16 activation probe for **1.7B and 4B
  only** using existing portable Torch/Transformers packages. Four distinct,
  matched productive/repetitive cases are the minimum. It records residual
  outputs and MLP-writer contrasts without gradients. Tensor names and shapes
  were verified for all four supported files, without GPU allocation.
  This optional Torch capture path remains separately unvalidated. The new native
  probe below supplies actual quantized activation capture for all six variants,
  including both 27B models, without a Transformers upgrade.
- `native_probe.py` / `verify_native_abi.py`: bounded llama.cpp C-API callbacks,
  pinned to the installed b10935 build and library hashes. Portable clang verifies
  every ctypes structure offset against the pinned headers. CUDA must load from
  the portable runtime; silent CPU fallback is refused. Callbacks retain at most
  32 rows per requested residual/MLP tensor and teacher-forced batches are bounded.
  Capture on/off produced identical tested logits for the 1.7B and 27B standard
  smoke cases. `native_probe_smoke.py` reproduces those numerical checks.
- `native_calibration.py` / `calibration_pairs.json`: per-model residual contrasts,
  64-column down-projection interventions, and matched controls. The existing
  GPU lease, native model tokenizer and owned worker lifetime are retained.
  Every scaled perturbation is capped at 15% of that matrix's Frobenius norm.
- `prepare_task_controls.py` freezes candidate/site/dose using calibration only.
  `run_task_controls.py` compares unchanged/candidate/random generations on the
  same held-out tasks and sampling seed. `run_loop_followup.py` checks the observed
  standard 4B selection cutoff with a 6,144-token budget and three seeds.
  `summarize_native_edits.py` rebuilds the bounded reports from preserved results.
- `probe_baseline.py` / `run_owned_probe.py`: an optional direct Torch diagnostic
  using the same installed GGUF tensors, a job-owned start gate, bounded lifetime,
  and the pinned model generation configuration (including both end tokens).
  It does not launch the native server. Its speed and numerical behavior must
  not be reported as native-runtime performance. An initial probe without the
  authoritative end-token configuration was invalidated and excluded; continuing
  after a completed answer is a probe defect, not evidence for a model edit.
- `sparse_edit.py`: CPU algebra and GGUF adapter export for one or two investigated
  MLP down-projection sites, at most 64 writer columns per site. It validates base
  and capture provenance, saves a separate additive rank-one adapter, and creates
  a norm-matched orthogonal random control. Originals are opened read-only.
  The adapter equation is `delta_W = -dose * outer(u, mask * (u @ W))`.
  This is a quantized-runtime adaptation, **not a bit-identical recreation of the
  authors' BF16 overwrite**. Native loading and behavioral effects have now been
  measured; working adapter loading is not evidence that an edit is beneficial.
- `research_guard.py`: a manual experiment-only pause shared by the native and
  Torch runners. Any `GPU-PAUSED.json` marker blocks startup, including an empty or
  malformed file. Hashing, loading and case boundaries check for a new pause.
  Native requests already in flight finish before the next check; this is not an
  immediate process termination mechanism. The guard never resumes automatically.
- `fetch_native_headers.py`: downloads a bounded set of upstream C-API headers
  and graph definitions pinned to the installed native build. Header provenance
  and the independently compiled ABI report accompany the native probe.
- `test_lab.py`: fourteen offline checks covering algebra, unchanged columns,
  equivalent matrix application, control norm/orthogonality, invalid inputs,
  adapter round-trip, data separation, loop detection, restricted code grading,
  host-I/O rejection, termination of an infinite loop, pause admission and
  interruptible model hashing. These checks do not load a GPU model.

The loop metric is advisory: a long unfinished answer is not automatically a
reasoning loop. Tool-workflow repetition and missing web evidence are separate
harness problems. The r62 photo fix addresses missing image evidence and likely
placeholder downloads; it does not constitute a weight change.

## Portable use

Place this folder under `PortalAI Windows/Maintenance/Research/Weight-Space-20261103`.
Run with the installation's `Runtime/BootstrapPython/python.exe -B -I`.
The source repository does not embed model weights, the tokenizer, GGUF's
third-party wheel, certificates, or local generation traces.

`prepare_reader.py` installs only the verified GGUF reader wheel into
`reader-packages`, reusing the existing portable NumPy layer. The prepared copy
uses gguf 0.19.0, wheel SHA-256
`70bcd10edfe697fb2dad6e40af2234b9d8ece9a41a99761405121ebda1c3c1cd`.
The tokenizer/configuration files come from `Qwen/Qwen3-1.7B`, revision
`70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, and are stored in `tokenizer-qwen3`.
Capture checks vocabulary IDs against each installed GGUF before use. No host
Python packages, services, model weights or production runtime upgrades are
installed. Optional loopback TLS uses disposable, experiment-local certificates;
certificate verification is never disabled.

Example native baseline, when GPU resources are available and any manual pause
marker has been explicitly cleared:

```powershell
& '.\Runtime\BootstrapPython\python.exe' -B -I '.\Maintenance\Research\Weight-Space-20261103\benchmark.py' --models 1.7-standard 1.7-abliterated --output baseline-new
```

This launches the experiment only; it does not change Nice's active model. A
separate output directory is required for every run. `--adapter` accepts one
model-specific, hash-verified candidate. `--split heldout` is reserved for a
candidate frozen after selection. Native baseline and candidate settings must
match. The current pilot uses 3,072 output tokens and 8,192 context tokens;
truncated cases need a separate matched, larger-budget check before diagnosing
model defects. Tool-selection tests use a small synthetic schema, not the whole
PortalAI harness, and therefore cannot prove end-to-end tool reliability.
Completed JSONL case records from a stopped run are preserved. Run the pending
models into a new output directory; there is no automatic retry or auto-resume.

## Acceptance before deployment

1. Reproduce actual looping failures and distinguish budget exhaustion, bad
   sampling, insufficient tool evidence, and harness loops.
2. Capture matched productive/repetitive activations from each affected model.
   Select candidate sites on selection data only; do not inspect held-out answers
   while choosing directions, layers, columns or dose.
3. Compare multiple doses, each site separately, the combined edit, and the
   norm-matched random control. Check teacher-forced loss on productive and
   repetitive continuations as well as generated answers.
4. Expand the frozen held-out set substantially, with real code tests, varied
   mathematical tasks, multi-turn tool fixtures, and normal conversation. Compare
   original/candidate using matched prompts, sampling, seeds and token budgets.
   Report rescues, regressions, confidence intervals, cutoff rate, latency and
   memory. Reduced output length alone is not a quality improvement.
5. Test native quantized deployment and cancellation. Reject unhelpful candidates.
   Only measured useful edits are eligible for D/E installation and installer
   integration. No automatic promotion or overwrite is implemented here.

The portable research files occupy tens of megabytes, primarily the shared
tokenizer. A tested single-site 27B adapter occupies about 88 KiB, including
metadata. Experimental adapters/captures use only a few additional megabytes;
no extra full-model copy or runtime was downloaded. The native runner preserves
an 80 GiB free-space floor. D and E hold independent source/dependency/evidence
copies; rejected adapters stay outside production and installer payloads.
