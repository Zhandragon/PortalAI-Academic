# PortalAI r75 — optional model downloads

Install PortalAI with separately licensed model choices left unchecked. Review publisher sources, licenses and restrictions before authorizing selected model downloads and their model dependencies. The purchase covers the harness; named models and LoRAs are optional, suggested/supported examples.

Custom chat imports accept a different compatible single-file dense Qwen3 GGUF model with an embedded chat template. Provide its direct HTTPS file URL, publisher SHA-256, exact size, label, variant and license URL. Setup checks the pin, GGUF metadata, architecture and tensor extents before publishing the file. The runtime checks it again before first use and after modification. Select the custom model manually in Settings; it is not added to Automatic selection. Vision, media models, adapters and split GGUFs need their own workflow contracts and are not interchangeable imports.

Academic retains its exclusions: standard variants only, no abliterated suggestions or coding specialist, and known excluded custom-model hashes are rejected. Existing models and accounts are preserved by normal protected updates.

Windows has model-group selection and license review. The experimental macOS/Linux installers offer small chat-model checkboxes and the compatible custom input. Universal setup prepares the corresponding three native installers. Physical Mac/Linux execution has not been newly validated.

Validation includes consent/dependency guards; invalid, truncated and overlapping GGUF rejection; custom install receipts and changed-file detection; Academic exclusions; native chooser tests; runtime policy tests for both editions; installer/preparation tests; and trial expiry/retained-state tests using the bundled Python 3.12 cryptography. A real local Qwen3 GGUF passed structural admission. These checks do not certify arbitrary custom models' inference quality.

Existing follow-up sending, science tools, GUI previews, platform dependency pins and edition boundaries are retained. Payhip Full and its free three-day trial use separate unbundled delivery kits; the drive mirrors retain the bundled edition installers.

## Licensing review

MusicGen/MMAudio weights are noncommercial; the Apple DFN5B-CLIP dependency in the MMAudio group is more narrowly limited to noncommercial scientific research, excluding commercial products/services and product development. FLUX variants, Swift and other dependencies have separate conditions. The license review shows these restrictions; choosing a URL does not grant additional rights.

The dependency audit also records GPL/LGPL/AGPL source obligations, vendor runtime conditions, and unresolved provenance/notice questions. It is not a legal clearance. See [the audit findings](DEPENDENCY-LICENSE-REVIEW-20261109.txt). PortalAI's existing GPLv3 and included third-party rights remain in force.
