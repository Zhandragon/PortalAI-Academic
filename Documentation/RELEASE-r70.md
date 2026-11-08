# Windows r70 — optional coding specialist

Full can route a coding request from the general uncensored 27B model to Swift 1.5 Qwen3.8 27B Abliterated Q4_K_M, then restore the saved general model after that request. Chat, context, tool results and permission checks are retained. Manual small/standard model selections and weight-edit profiles are respected. Stop, changed settings, listener ownership and actual GPU memory admission guard the switch; unavailable specialists fall back before inference.

The optional model and matching projector add 16.52 GiB, with pinned revisions and hashes. [The six-task local comparison](../Research/CodingSpecialist/README.md) produced 5/6 correct implementations versus 1/6, 44.5% fewer tokens and 41.5% less inference time. One Swift task still exhausted its token budget. This is a limited diagnostic on a 3090, not a broad benchmark; loading and return-switch time are additional.

The shared software is updated in both editions. Academic retains standard-only model policy and excludes the abliterated component. New installations default automatic coding routing to off; installed owners can choose it in Settings → Chat. The tested D/E Full installations enable it explicitly at their owner's request.

Upgrade packages retain previous compatible versions and legacy fingerprints, preserve accounts/data/model choices and original model files, and now preserve `Agent/storage_reserve.json` along with storage preferences. The owner-selected 50 GiB reserve is retained on D/E; defaults for new installations are unchanged. No new Python runtime or inference libraries are added. Linux/Mac installers remain r51.

Validation includes the exact-model comparison, independent D/E load → specialist/tool protocol → return checks, routing/settings/cancellation/runtime tests, disposable upgrade and rollback tests, installer dependency planning, and archive/payload SHA-256 readback. Full-size fresh recipient installs were not performed. Installer verification is recorded in [WINDOWS-INSTALLER-r70.json](WINDOWS-INSTALLER-r70.json).

The separate weight-space experiment remains paused, with no promotion or original-model replacement.
