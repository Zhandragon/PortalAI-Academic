# Windows r68: native presence-penalty repair

The Weight-Space Editor now applies nonzero presence penalties to a positive history covering the complete generated reply. The pinned llama.cpp runtime clamps the old negative history length to zero, which silently disabled this penalty. Saved generations now identify the corrected sampling implementation and history settings. Normal chat-server sampling is unchanged.

Earlier 27B research requested 1.5 but actually ran with zero. Those original records and ledgers are preserved, marked superseded, and the tests are being rerun with the same cases and seeds. Completed 1.7B/4B comparisons requested zero and are unaffected. None of the completed edit comparisons has established an overall improvement; original model files remain unchanged. [Correction and research](https://github.com/Zhandragon/PortalAI-Academic/tree/main/Research/WeightSpace/InstalledGGUF).

Reversible optional profiles remain under Utilities > Weight-Space Editor and Settings > Chat models > Weight edit profile. Select Original weights to revert. The patches are small, but a prepared model occupies its full model size. The two-copy cache and **80 GiB free-space floor** remain. No automatic profile selection or tool replay is added.

**Validation:** 92 focused checks on D, E and each extracted edition (one platform-related skip per run). The new regression failed before the repair; actual native DLL sampling verifies the corrected penalty without loading a GPU model. Both editions also passed 45 installer checks (one platform skip), seven embedded-source/runtime checks, 55 native-file checksum checks, and upgrade planning from all **27** supported previous stamps. The Academic compiled launcher passed prepare-only verification. Every application source matches its packaged payload. Python package fixtures came from D; a complete fresh-recipient installation was not tested.

Added application content: **8,151 bytes** versus r67. All runtime/model component pins are inherited unchanged; no new model, dependency, service or duplicate runtime is added. D and E keep independent installations and installer kits. Linux/Mac remain r51. Restart the editor normally to load the repair; already-running workers retain their loaded code until exit.

[Repair details](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/WEIGHT-SAMPLER-r68.md) · [Validation evidence](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/WEIGHT-SAMPLER-VALIDATION-r68.json).
