# Windows r66: bounded coding evaluation

A generated program that runs past the five-second limit now scores as an incorrect answer after its owned worker stops, allowing the weight-space comparison to continue. Infrastructure failures and non-coding grading timeouts still raise errors.

Reversible profiles remain available under Utilities → Weight-Space Editor and Settings → Chat models → Weight edit profile. Select Original weights to revert. Existing original models and account preferences are unchanged. Compact patches require full-size prepared model copies for loading; the two-copy cache and **80 GiB free-space reserve** remain enforced.

Both evaluated 1.7B discovery edits failed the improvement gate: standard 18/28 versus original 18/28 and random control 19/28; abliterated 18/28 versus original 20/28 and random control 20/28. They are optional experiments, not recommended replacements. Larger-model testing is ongoing. [Exact recipes and current research](https://github.com/Zhandragon/PortalAI-Academic/tree/main/Research/WeightSpace/InstalledGGUF) · [Optional profile downloads and tradeoffs](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Research/WeightSpace/InstalledGGUF/OPTIONAL-PROFILES.md). The r65 profile files remain compatible with r66.

**Validation:** 87 focused checks passed on D, E and both extracted packages, with one platform-related skip per run. Tests include a real non-terminating program, confirmation that its worker stops, and successful grading of the next program. Each edition passed 45 installer checks (one platform-related skip), seven embedded source/runtime checks and upgrade planning from all **25** supported prior version stamps. The Academic compiled launcher passed prepare-only verification. Every application source matches its packaged payload. The complete r65 suite and native profile-switch results remain historical evidence; this grading-only patch did not repeat live GPU switching. A fresh-recipient full installation was not performed.

Added application content: **3,402 bytes** versus r65. No new dependency tree, runtime or model download. Both portable SSDs retain independent installations and installer kits. Linux/Mac remain r51. Restart PortalAI normally to load the repair.

[Repair details](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/WEIGHT-GRADING-r66.md) · [Validation evidence](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/WEIGHT-GRADING-VALIDATION-r66.json).
