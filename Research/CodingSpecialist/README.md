# Swift coding specialist: bounded local acceptance

This is a six-task diagnostic of the exact installed GGUF files on an RTX 3090, not a general intelligence evaluation or a broad coding leaderboard. No PortalAI weight-space edits were performed; that independent study remains paused.

Compared models: the existing Qwen3.8 27B Abliterated Q4_K_M and grimlee Swift 1.5 Qwen3.8 27B Abliterated, Q4_K_M quantization by mradermacher. Both used the same runtime/CUDA library hashes, 8192 context, seed 46, temperature 0.6, top-p 0.95, top-k 20, xhigh thinking, and 4096 maximum generated tokens. The protocol was fixed before the runs. Each model ran once per task; there is no repeated-seed estimate or confidence interval. Startup/model switching is excluded from inference timing.

| Result | Original | Swift |
| --- | ---: | ---: |
| Functionally correct completed tasks | 1/6 | 5/6 |
| Generated tokens | 21601 | 11989 |
| Inference seconds | 582.578 | 340.842 |
| Token limit reached before final code | 5/6 | 1/6 |

Swift preserved the baseline's successful case and solved four more, using 44.5% fewer tokens and 41.5% less inference time. It still exhausted the budget on JSON pointer. Exact repeated 48-word spans were zero in both models; token exhaustion is not proof of a semantic reasoning loop. The result supports an optional coding route on this machine, not universal superiority, elimination of loops, or faster tokens per second. Model loading can outweigh the saving on short tasks.

The task prompts, raw responses, per-task timing, grader results, and runner are included here. The recorded protocol SHA-256, computed from `json.dumps(protocol, sort_keys=True)` encoded as UTF-8, is `8dc7c2895488ca9460cbf7454234ff7d51e0cb0f677d49b2c8f442848aff5147`. The raw `comparison-protocol.json` file SHA-256 is `d375b129391023e47314c0647a0cceff633ab5f94ae991ba6e872cb6cb8d6b5d`. Assertions validate implementations in bounded child processes; returned code is screened before execution. The runner's portable paths are examples of the tested installation, not required drive letters.

Model and projector together: 17,738,323,200 bytes (16.52 GiB) per drive. Each installation has an independent real copy. Pins and license are documented in [the application guide](../../ApplicationSources/Windows/PortalAI/Documentation/Coding_Specialist.md). The upstream author's published evaluation is not substituted for these exact-quantization results.

Separate live D/E checks exercise the actual model manager: original model readiness, automatic specialist preparation, an OpenAI-format `read_file` tool call and synthetic result continuation, then return to the original model. No external tool or owner account data is used by those checks. Saved selection bytes must remain unchanged. Unit tests cover cancellation, model ownership, memory admission, manual overrides, upgrade discovery and storage reserve preservation.

The Full installer offers Swift as an optional component. Academic retains its standard-only policy and does not bundle or route to this abliterated model. Existing original weights are preserved. Automatic routing can be disabled; manually selecting Swift retains it across requests. All model/tool rounds of one foreground request use one model, with restoration afterward; subsequent coding follow-ups may incur another load.
