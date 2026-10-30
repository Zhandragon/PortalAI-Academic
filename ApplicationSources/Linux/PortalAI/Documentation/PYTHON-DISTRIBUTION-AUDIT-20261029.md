# Python distribution audit — 2026-10-29

Read-only analysis of D: and E: only. No Python, NumPy, package, runtime selector or launcher was merged, replaced or deleted. The deprecated C: installation was not inspected. Interpreter probes ran only isolated `-B -I -S` standard-library code; this is not a new GPU/model acceptance run.

There are **14 interpreter/launcher candidates on each SSD**, excluding Python's venv template executables and historical recovery copies. Multiple Python minors and incompatible native/GPU stacks justify separate package environments. A shared interpreter core is feasible for some same-minor groups, but a single combined Python/site-packages directory is not a safe conversion.

## Dependency map and feasibility

Versions below are actual executable probes. Package versions come from installed distribution metadata; importing all ML packages or checking their complete compatibility was outside this read-only inventory. Paths are relative to each SSD's `PortalAI Windows`.

| Interpreter/launcher | D: / E: Python | Current dependents | Consolidation assessment |
| --- | --- | --- | --- |
| `Runtime/BootstrapPython/python.exe` | 3.12.14 / 3.12.14 | Native GUI/chat, missions, API, knowledge, artifact preview worker, science adapters, Piper/STT layers; Qwen TTS uses it with its own packages. | Keep as the orchestration base; sharing its executable is already supported by several adapters. |
| `Generative/ComfyUI_windows_portable/python_embeded/python.exe` | 3.12.14 / 3.12.10 | ComfyUI/image/video CUDA services via Agent/service_manager.py. Torch 2.13.0+cu130. | Same Python minor as Bootstrap, but different environment layout and GPU package stack. A shared core is technically possible after launcher/embedded-path tests; do not merge packages. |
| `Music/ACE-Step-1.5/python_embeded/python.exe` | 3.11.17 / 3.11.9 | ACE-Step music server via Agent/service_manager.py. Torch 2.7.1+cu128; Transformers 4.57.6. | Could share a carefully rebuilt 3.11 core with MMAudio while retaining separate package layers. Not a drop-in directory merge. |
| `Runtime/MMAudioPython/python.exe` | 3.11.17 / 3.11.16 | MMAudio SFX via Agent/sfx_bridge.py. Torch 2.5.1+cu121; NumPy 2.0.2. | Keep packages separate from ACE-Step and ComfyUI. Different Torch/CUDA/NumPy requirements. |
| `MusicUnderstanding/runtime/python.exe` | 3.12.10 / 3.12.10 | Windows music specialist worker runtime: MOSS, CLAP, Demucs. Torch 2.9.1+cu128; Transformers 4.57.1. | Possible shared 3.12 core only after specialist tests; preserve its _pth and package layers. Contains old cp313 artifacts alongside cp312 files, so a blanket path merge is unsuitable. |
| `Runtimes/Python310/cpython-3.10.21-windows-x86_64-none/python.exe` | 3.10.21 / 3.10.21 | MuseTalk via Agent/musetalk_runtime.py, which explicitly requires Python 3.10 and loads Video/MuseTalk/.venv/Lib/site-packages. Torch 2.0.1+cu118, mmcv 2.0.1, mmpose 1.1.0, NumPy 1.23.5. | Keep separate. cp310 native extensions cannot simply be loaded by Python 3.11/3.12. |
| `Video/MuseTalk/.venv/Scripts/python.exe` | launcher fails / launcher fails | Old copied uv launcher. Current MuseTalk bridge bypasses it; its package tree is still active. | Launcher probe fails. This is not evidence that the package tree is unused or safe to remove. |
| `Voice/Qwen3-TTS/.venv/Scripts/python.exe` | launcher fails / launcher fails | Old uv launcher; current voice_bridge prefers BootstrapPython plus this venv package layer. Torch 2.14.0+cu126; Transformers 4.57.3. | Launcher probe fails, but these packages are active. Preserve the package layer. |
| `Voice/Qwen3-TTS/python/cpython-3.12.14-windows-x86_64-none/python.exe` | 3.12.14 / 3.12.14 | Legacy Qwen installation/fallback with a second large package tree; referenced by voice fallback and audit_specialist_filters.py. | Largest consolidation candidate: roughly 4.50 GiB of identical package files per SSD, but hundreds of differing/unique files. Needs a reviewed canonical package tree and updated fallback/setup references. |
| `Voice/Qwen3-TTS/python-base/cpython-3.12.14-windows-x86_64-none/python.exe` | 3.12.14 / 3.12.14 | Qwen Install_or_Repair_Qwen3_TTS.ps1 base interpreter for rebuilding its venv. | Small core duplicate. Could share an ABI-compatible base with relocated launchers; removing it without changing repair scripts breaks repair. |
| `Voice/Qwen3-TTS/python-bin/python3.12.exe` | launcher fails / launcher fails | Legacy uv-managed interpreter trampoline from Setup/Legacy/Install_Qwen3_TTS_Portable.ps1. | Probe fails. Retain until legacy setup/fallback policy is explicitly retired. |
| `OpenWebUI/python/cpython-3.11.16-windows-x86_64-none/python.exe` | 3.11.16 / 3.11.16 | Base for optional Open WebUI and its separate venv. | Keep its packages separate. A future common 3.11 base requires rebuilding the relocatable launcher and import paths. |
| `OpenWebUI/venv/Scripts/python.exe` | launcher fails / launcher fails | Optional OpenWebUI/*.bat starts portal_manager.py through this copied uv launcher. | Probe fails from both SSDs. These optional launch paths need a portability repair; not changed by this audit. Main native PortalAI is a separate route. |
| `Tools/KiCad/bin/python.exe` | 3.11.5 / 3.11.5 | KiCad embedded Python and pcbnew/wx/native DLL integration. | Keep vendor-owned. Version matching alone is insufficient for embedded KiCad binaries and DLL search paths. |

## Actual duplication versus separate environments

The Qwen `.venv/Lib/site-packages` and `python/cpython-3.12.14-windows-x86_64-none/Lib/site-packages` trees were compared by relative filename, byte count and SHA-256, excluding bytecode caches. This comparison did not modify either tree.

| SSD | Identical files | Identical logical bytes | Different files at matching paths | Only in venv / only in legacy base |
| --- | ---: | ---: | ---: | ---: |
| D: | 30,108 | 4,836,396,718 (4.504 GiB) | 272 | 179 / 283 |
| E: | 30,180 | 4,837,163,893 (4.505 GiB) | 200 | 112 / 283 |

None of those identical pairs were already hard-linked. This is a meaningful candidate, unlike the earlier ~40 MiB NumPy-only proposal, which remains cancelled. However, differing files include active `filelock` source, packaging helpers and distribution RECORD files, not merely harmless bytecode. Equal package version labels do not prove equal contents. The duplicate-byte total is an upper candidate estimate, not an approved reclaimable amount or a safe deletion list.

On D:, the Bootstrap/Comfy pair shares 12 measured top-level executable/DLL/archive files totaling 20.98 MiB. MMAudio/ACE shares 13 such files totaling 19.92 MiB; the Qwen base/legacy pair shares 12 totaling 20.98 MiB. These measurements exclude the full standard library and package trees. They do not imply whole distributions are interchangeable. E: has different Comfy, ACE-Step and MMAudio interpreter patch versions; the two SSDs must not be assumed identical. The MuseTalk interpreter reports the same version on both but has different executable hashes.

Additional paths named `AccountPython`, `ScientificPython`, `AMDPython`, `ProteinDesign`, Piper and Knowledge often represent **package layers**, not another complete Python executable. Bootstrap selects their packages for specific workers. CUDA, ROCm and CPU Torch layers must retain their intended backend boundaries. Linux runtime layers also remain distinct from Windows binaries. Historical `*-inaccessible-*` and recovery copies are retained evidence, not approved cleanup targets.

## Portability findings and recommendation

Both SSDs have broken old uv trampolines for OpenWebUI, MuseTalk, Qwen TTS and Qwen `python-bin`. Their configuration refers to prior Desktop base-runtime locations. The current MuseTalk and Qwen voice adapters already choose an SSD-local executable and load their own packages, so their old trampoline failure does not establish a broken current feature. Optional OpenWebUI batch launchers still refer to its failing venv interpreter and warrant a separate repair. The duplicate copies under Launchers also use paths relative to their own directory; that legacy launch surface needs its own review.

If consolidation is later approved, the strongest candidate is the duplicate Qwen package installation, after choosing and validating a canonical set and fixing every fallback, repair and audit reference. Keep MuseTalk's cp310 stack, KiCad's embedded runtime and mutually incompatible ML package sets separate. Sharing a 3.11 or 3.12 interpreter **while retaining isolated package layers** is technically possible, but its small core savings alone do not justify an automatic migration here.

A future migration would need per-component import and real inference checks, DLL-resolution and package-origin verification, repair/update tests, relocation to another drive letter, and rollback on each independent SSD. No link should require the other SSD or a C: runtime. No hard-link or junction conversion was performed.

The rationale follows Python's documented [C API/ABI boundaries](https://docs.python.org/3/c-api/stable.html) and [virtual-environment portability limits](https://docs.python.org/3/library/venv.html): ABI compatibility within a minor version depends on compatible builds, and copied venv launchers can retain absolute paths. These rules support the assessment; they do not substitute for PortalAI's own functional tests.

Evidence on each SSD: `Maintenance/Validation/Integration-20261029/python-distributions.json` and `qwen-duplicate-comparison.json`. Raw reports contain machine-specific configuration paths and remain local. Reproducible read-only inventory source: `Tools/audit_python_distributions.py`. The hash comparison used Python's streaming SHA-256 and file identity metadata; all differing paths are retained in its local report.
