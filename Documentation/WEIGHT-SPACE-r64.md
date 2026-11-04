# Windows r64: portable weight-space editor

Open **Controls → Utilities → Weight-Space Editor**, or launch `Utilities/PortalAI Weight-Space Editor/Start Weight-Space Editor.cmd` on the portable drive. Choose a GGUF model, inspect its eligible tensors, evaluate a discovery task file, locate possible failure sites, create a separate candidate from an edit recipe, and compare original/candidate behavior. Work and evidence stay on that drive.

The editor accepts user-selected compatible GGUF files. It does not support every architecture or storage format. Native evaluation currently requires Windows x64, NVIDIA CUDA and the pinned portable llama.cpp build. Editing supports the listed dense MLP down-projection quantizations; incompatible layouts and importance-matrix-dependent encoders are refused. It reuses the installation's voice Python packages for NumPy/Jinja/SymPy, so those components must be present. There are no new model downloads, full training runtime or resident background service.

## What the edit does

For measured unit direction `u`, selected writer columns `S`, and a tested dose, the CPU editor subtracts `dose * outer(u, mask_S * (u @ W))`. It opens the original read-only, copies it to a new candidate, and re-encodes only affected GGUF quantization blocks. Neighboring values within those blocks can also change; receipts measure the actual perturbation and quantization error. Unaffected blocks, embeddings, final normalization and output weights remain unchanged. At most two dense MLP sites and 64 columns per site are allowed, with a 15% matrix-relative perturbation ceiling.

This is an adaptation of [Takehi et al.'s weight-space programming experiment](https://rikiyat.github.io/blog/weight-space-programming/) to PortalAI's actual installed quantized models. It is a direct serialized weight edit, not merely a prompt instruction or diagnostic adapter. The authors used BF16 weights and vLLM; this implementation uses quantized llama.cpp. During the research workflow, additive adapters provide inexpensive site/dose controls, followed by generation from an actual edited GGUF. This Codex session acts as editor; a separate identical Astra run is not claimed.

Natural success/failure contrasts suggest hypotheses. They can reflect topic or difficulty and are not proof of a looping mechanism. A favorable diagnostic loss or a few rescued answers is not a general intelligence result. Use isolated site/dose tests, zero-dose and norm-matched random controls, then freeze the candidate before independent tests. User task-file comparisons are discovery evidence, not automatic certification.

## Files, recovery and limits

- Original models are never replaced by the utility. Each candidate has a checksum-bound recipe and edit receipt. Output inside the production model directory is refused.
- Creating a candidate needs about one model-sized temporary copy plus evidence space. Every operation reserves at least **80 GiB free**. A standard 27B candidate therefore needs roughly 18 GiB of additional working space.
- The GUI launches bounded owned workers, polls a small log tail and remains usable while work runs. Stop/Close terminates only its worker tree. Large models still require substantial GPU memory and generation time.
- A durable campaign ledger accounts for 50 discovery/confirmation passes and 300 CPU editing actions. Interrupted passes require review; they are not silently replayed. A new campaign preserves earlier evidence.
- Coding checks deliberately permit only restricted pure functions in time/memory-bounded workers. They are not a general OS sandbox. Tool selection is graded without executing model tool calls.
- Historical upgrades preserve the updater's existing application-root boundary. On first launch, PortalAI creates a missing sibling utility launcher from its packaged template without overwriting an existing customized entry point.

The installer repair also fixes a version mismatch: r63's sidecar listed recent versions while its embedded upgrade contract remained r51. r64 embeds the complete retained history and matches its sidecar. Synthetic upgrade planning checks cover all 23 supported prior version stamps; inherited legacy fingerprints are retained. This does not promise upgrades from arbitrary unrecognized modifications.

## Source and validation

- [Editor, direct subtraction, native forward tools and guide](../ApplicationSources/Windows/PortalAI/Tools/WeightSpace/)
- [Portable launcher](../ApplicationSources/Windows/Utilities/PortalAI%20Weight-Space%20Editor/)
- [Utilities registration](../ApplicationSources/Windows/PortalAI/Agent/suite_utilities.py)
- [Regression checks](../ApplicationSources/Windows/PortalAI/Maintenance/Tests/test_weightspace.py)
- [Installer builder](../tools/build_weight_space_windows_release.py)
- [Release validation](WEIGHT-SPACE-VALIDATION-r64.json)
- [Research history and current status](../Research/WeightSpace/README.md)

The r64 utility release makes **no production model replacement or broad intelligence improvement claim**. The six-model study uses standard/abliterated 1.7B Q8_0, 4B Q4_K_M and 27B Q4_K_M. Only candidates that pass independent paired confirmation, broad math/coding/tool/instruction checks and a latency gate can be considered for a later model replacement. Failed or incomplete evidence leaves the installed original in place. Linux/Mac application releases remain r51.
