# Automatic coding specialist

This feature belongs to Full. Academic preserves its standard-only model policy and does not install or automatically select the abliterated specialist. The comparison below concerns Full.

PortalAI can temporarily use Swift 1.5 Qwen3.8 27B Abliterated Q4_K_M for a coding request and return to the saved general model when the request ends. All model/tool rounds within that request use the same specialist. The chat transcript, attachments, context compaction, tool outcomes, permission checks and verification policy remain in place. The switch happens before inference; it does not replay a tool or retry a completed action.

In **Settings → Chat → Automatic coding specialist**, choose `automatic` or `off`. Automatic routing requires an installed, locally validated specialist, a full GPU fit, and an uncensored general 27B selection (`qwen27-q4` or `qwen27-q5`) or Deep Automatic with the uncensored preference. Small-model, standard-model and experimental weight-profile selections stay pinned. Select Swift directly in Chat model to keep it loaded, including for noncoding requests.

The bounded local classifier recognizes coding language, debugging, source attachments and short coding follow-ups. It is a heuristic: ambiguous requests may remain on the general model. It reads user messages, not instructions inside tool results. A coding request ends when its foreground worker finishes all inference/tool rounds; a follow-up is a new request and can select Swift again. This adds model-loading time at both boundaries; it is most useful for substantive coding work. A Stop, revoked login, changed settings, replaced listener or insufficient memory prevents an unsafe switch. No two chat models are deliberately loaded together. Failure to prepare Swift falls back to the saved general model before inference; failure to return leaves the saved preference unchanged for the next request.

This route is used by native chat, including requests submitted through its remote/voice entry points. Standalone scheduled mission workers retain their existing model policy.

## Files and evidence

The optional model and matching F16 vision projector together occupy 17,738,323,200 bytes (16.52 GiB) per installation. Each SSD owns its own files; neither installation depends on the other drive.

Quantization repository: <https://huggingface.co/mradermacher/Swift-1.5-Qwen3.8-27B-Abliterated-GGUF>

Pinned revision: `ded51b02bf1efb330c9c032f810e881f1c3dd2f7`.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| Swift-1.5-Qwen3.8-27B-Abliterated.Q4_K_M.gguf | 16810715648 | 8a9d05004721247a3206400818b6047fe7581f1cf3dc87231263770e802b85da |
| Swift-1.5-Qwen3.8-27B-Abliterated.mmproj-f16.gguf | 927607552 | 3924c7fa4d7f154163e6b633d9e94a6b419b222bebbaf8ea618a05df1264a14b |

Source: `grimlee/Swift-1.5-Qwen3.8-27B-Abliterated` at `0e35abf5d32233d3b574ed1b8951264221b8872d`, derived from UkisAI Swift 1.5. License and attribution are under `Documentation/ModelLicenses/Swift-1.5/`. PortalAI performs no additional weight edits.

Swift's published efficiency measurements concern the upstream model. They do not establish that this particular abliterated Q4 file retains the gains. The source author's HumanEval+ card and uploaded report also differ; no universal coding improvement is asserted. Local acceptance therefore compares the exact quantization against the installed general Q4 model with identical prompts and generation settings, checking correctness, generated tokens, inference time and repetition. This small diagnostic is not a broad benchmark. The `coding_route_validated` catalog flag remains false until that comparison is reviewed.

Original general models and their selection are retained. The separate weight-space experiment stays paused. Model updates must preserve user settings, original GGUF files, model licenses and the configured SSD reserve.

## Local acceptance, 2026-11-07

On one RTX 3090, six fixed Python implementation/debugging tasks were compared at the same Q4_K_M precision, seed 46, temperature 0.6, top-p 0.95, top-k 20, 8192 context, xhigh thinking and a 4096-token reply cap. Identical runtime executables/CUDA libraries were verified across D/E. Assertions checked each returned implementation in a bounded child process. The protocol and complete responses are published under `Research/CodingSpecialist` in the source repositories.

| Result | Existing Qwen 27B Abliterated Q4 | Swift 1.5 Abliterated Q4 |
| --- | ---: | ---: |
| Correct completed implementations | 1/6 | 5/6 |
| Generated tokens, total | 21601 | 11989 |
| Inference seconds, total | 582.578 | 340.842 |
| Reply-budget exhaustion before an answer | 5/6 | 1/6 |

Swift used 44.5% fewer generated tokens and 41.5% less inference time in this small diagnostic. It preserved the baseline's successful case and completed four additional tasks correctly. The JSON-pointer task still overthought and exhausted the budget. Exact repeated 48-word spans were zero in both models; budget exhaustion is evidence of unfinished reasoning, not a formal semantic loop detector. No universal speed, reasoning-loop elimination, or leaderboard improvement is claimed.

Timing excludes model loading and return switching. Those costs can outweigh the inference saving on a short request; retaining Swift manually is available for extended coding sessions. The catalog acceptance flag is enabled only for these pinned model files. Runtime memory admission and cancellation remain separate gates.
