# Weight-space experiment: reasoning, coding, math and tools

**Status: experimental preparation, not an installed model improvement. No model
weights have been changed, no candidate has been accepted, and no quality gain has
been established.** After the user stopped the interfering antivirus shields,
native inference resumed and all 48 selection cases on the four 1.7B/4B variants
completed. GPU experiments are now manually paused while the user plays a game;
the two 27B variants remain pending. Existing originals and the production model
selection remain unchanged.

Native strict passes were **9/12 standard 1.7B, 10/12 abliterated 1.7B,
10/12 standard 4B, and 8/12 abliterated 4B**. These are tiny selection diagnostics,
not general model rankings. Review separates correct mathematics with formatting
errors from actual coding and tool-selection failures. One standard 4B coding
response exhausted its 3,072-token allowance; the advisory repetition detector
flagged none. Repeated self-checking still warrants a matched larger-budget
follow-up; neither a cutoff nor a negative detector proves whether a loop exists.
See [native results and reviewed limitations](NATIVE-PILOT-RESULTS.json).

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
  Actual activation capture and numerical comparison remain unvalidated.
  **27B activation capture is not implemented:** its hybrid architecture and
  memory needs require a compatible quantized activation backend. Native 27B
  baselines are supported, subject to available VRAM.
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
  authors' BF16 overwrite**. Native adapter loading and behavioral effects have
  not yet been validated.
- `research_guard.py`: a manual experiment-only pause shared by the native and
  Torch runners. Any `GPU-PAUSED.json` marker blocks startup, including an empty or
  malformed file. Hashing, loading and case boundaries check for a new pause.
  Native requests already in flight finish before the next check; this is not an
  immediate process termination mechanism. The guard never resumes automatically.
- `fetch_native_headers.py`: downloads a bounded set of upstream C-API headers
  and graph definitions pinned to the installed native build, for preparation
  of a quantized activation backend. Downloading these files does not implement
  or validate native activation capture.
- `test_lab.py`: twelve offline checks covering algebra, unchanged columns,
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

The prepared files are approximately tens of megabytes, primarily the shared
tokenizer. A two-site float32 rank-one adapter would contain roughly 64–176 KiB
of tensor data depending on model dimensions, plus metadata; this is an estimate,
not a validated deployed adapter size. The native runner preserves an 80 GiB
free-space floor. D and E hold independent copies of the preparation.
