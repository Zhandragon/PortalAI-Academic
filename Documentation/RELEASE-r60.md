# Windows r60 — verified results and capability intelligence

Adds independent result checks; bounded external project maps, change previews and conflict-aware undo; memory correction and temporary facts; structured document retrieval; optional measured model recommendations; and Ctrl+K search with quiet completion notifications. Reviewed project test commands run in a bounded worker. Model calibration is opt-in and never silently applies a recommendation.

Published application growth from r59: **130,241 bytes** (about 0.13 MB). No new model weights, runtime or permanent background service. Both SSDs retain independent Full installations and an **80 GiB free-space floor**. Installer kits, recovery copies and user data are separate from program growth. Voice pitch, playback padding and existing compact layouts are retained.

Testing repaired the automatic knowledge-rebuild guard, minimal DOCX compatibility, a Windows child-log cleanup race and concurrent metadata publication. The latter retries only atomic record publication, rechecking Stop/account fences; it never replays the represented action. Kind-specific verification schemas require the expected JSON value while preserving legacy callers.

Validation: **666 checks on each D/E installation and each exact extracted edition: 665 passed, one platform skip**. Each edition also ran 45 installer checks (44 passed, 1 skipped), and passed seven embedded-resource checks and catalog routing checks. The compiled Academic download launcher passed preparation checks. Real project-worker execution, stale-result rejection, child timeout and uncertain-repeat blocking passed. Encrypted-profile sealing/reopen, memory correction, guarded undo, retrieval, Stop and automated hidden-Tk UI checks passed.

On this RTX 3090 machine, a real 1.7B write-and-independent-verify request finished in **7.94 seconds**. Both 1.7B and 4B completed the optional eight-question calibration at 6/8, in about **43 seconds combined including loading**. Synthetic document indexing took **0.89 s**, search **0.016 s**. GUI timer lateness was about **12 ms p95**, with a **558 ms maximum** in the disposable window; this is not a guarantee for other hardware or all GUI actions.

Limits: separate 4B agent attempts produced invalid multi-tool batches and were safely stopped for review. Calibration does not guarantee task success. Computer Use was stopped with Escape, so desktop visual inspection is incomplete; automated GUI checks passed. Other physical hardware tiers and a complete fresh recipient installation were not tested. Result predicates establish only what they explicitly check. Unknown external effects are not automatically replayed.

D and E installations and their installer kits are updated independently. The deprecated C installation is excluded. Windows is r60; Linux/Mac remain r51. **Exit and reopen PortalAI normally** to load the update.

[Features, source and limits](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/CAPABILITY-INTELLIGENCE-r60.md) · [Validation](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/CAPABILITY-INTELLIGENCE-VALIDATION-r60.json).
