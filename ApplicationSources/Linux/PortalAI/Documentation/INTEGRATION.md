# Structured output, application API and interactive artifacts

The Workspace integration patch adds three tabs to the existing native Workspace sheet: **Structured**, **API**, and **Artifacts**. Open Workspace from Chat or the launcher menu. The eleven main pages and six Controls buttons are unchanged. This patch uses the existing bundled Python, Knowledge JSON Schema package, and portable Web/Chromium runtime. It installs no host service, Python, Node, package manager or extra model.

## Structured output

Start a local chat model. In **Workspace → Structured**, enter a question, source context and JSON Schema, then select **Generate JSON**. The `structured` chat tool and workflow `prompt` steps with a `schema` argument use the same implementation. API clients use `POST /v1/structured` and poll the returned job.

The backend receives `response_format.type=json_schema`. The prompt separately describes the schema. Completed output is independently validated; duplicate JSON keys, non-finite numbers, truncated answers and unexpected tool calls are rejected. Backend rejection is reported, without silently falling back to unconstrained generation. A valid schema result does not establish factual correctness.

Supported schema subset: one explicit type per node (`object`, `array`, `string`, `integer`, `number`, `boolean`, `null`); object properties and required fields; boolean `additionalProperties`; array items and item-count bounds; string-length bounds; enum/const; integer numeric bounds; standalone `oneOf`/`anyOf` alternatives. Object schemas default to `additionalProperties:false`. Unsupported keywords such as references, formats, patterns and conditional schemas are rejected. Nullable values use a union with a null schema. Limits: 64 KiB schema, 12 nesting levels, 512 nodes, 64 properties per object, 32 alternatives, 128 KiB prompt input and 1 MiB model response. Context and output must fit the running model.

Mission planning now generates a closed, mode-specific action schema from `mission_modes.allowed_actions`. Observe cannot generate a shell action. Existing mission permissions, semantic checks, step budgets, pending-action receipts and uncertain-effect review still apply. Nothing here grants a mission additional authority or replays an uncertain action.

Source: [structured_generation.py](../Agent/structured_generation.py), [mission_runner.py](../Agent/mission_runner.py), [capability_tools.py](../ControlCenter/capability_tools.py). Backend contract: [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) and [supported grammar/schema features](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md).

## Application API v1

Sign in as an administrator and open **Workspace → API**. Choose **Start API**, copy its live URL, select explicit scopes and issue a named token. The token is shown once; only its SHA-256 hash is saved. Grants expire in 1–720 hours and can be revoked. The API binds only to `127.0.0.1` on a fresh port. It rejects browser Origin headers and unexpected Host headers, has no CORS grant, and creates no LAN listener or firewall rule.

The server runs while that Workspace sheet is open. Closing it, sign-out, exit or Stop closes the listener and cancels API jobs. A revoked/expired token cancels its jobs at their next check. Jobs are tracked by the existing writer gate so profile sealing waits for writers. API service startup is always explicit; saved tokens do not auto-start it. The URL can change each start. Do not embed tokens in an HTML artifact or website; clients are trusted local applications.

Every response has `{"api_version":"1.0","data":...}` or an `error` object with `code` and `message`. Every POST requires JSON and an **Idempotency-Key** of 8–120 characters from letters, digits, underscore, dot, colon or hyphen. Generate and retain a key before sending; reuse it only for exactly the same request. The SDKs never automatically retry a mutation. A completed receipt returns its original result. A key reused with different content is refused. An interrupted pending receipt blocks both its original key and an equivalent request under a fresh key. Review uncertain requests explicitly in the native API tab; confirming records a reviewed result, and allowing retry does not itself run the action. Even a failed operation may have partial effects.

| Resource | Routes after the live `/v1` base | Scope |
| --- | --- | --- |
| Contract/status | GET `/status`, `/openapi.json` | Any valid token |
| API conversations | GET/POST `/chats`; GET `/chats/{id}`; POST `/chats/{id}/messages` | `chats:read` / `chats:write` |
| Typed extraction | POST `/structured` | `structured:generate` |
| Asynchronous jobs | GET `/jobs`, `/jobs/{id}`; POST `/jobs/{id}/cancel` | Only the creating token's jobs |
| Missions | GET/POST `/missions`; GET `/missions/{id}`; POST `/missions/{id}/start`, `/stop` | `missions:read` / `missions:write` |
| Document collections | GET/POST `/knowledge/collections`; POST `/knowledge/collections/{id}/sync` | `knowledge:read` / `knowledge:write` |
| Retrieval | POST `/knowledge/search`; GET `/knowledge/citation?citation=...` | `knowledge:read` |
| Generated files | GET `/outputs`; GET `/outputs/content?path=...` | `outputs:read` |
| Artifacts | GET/POST `/artifacts`; GET `/artifacts/{id}`, `/history`; POST `/revisions`, `/restore`, `/export` below the artifact ID | `artifacts:read` / `artifacts:write` |

API chats are separate persisted plain-text conversations, not edits to the live native Chat session. This channel does not execute model tools. Use the document, mission and artifact resources for application actions. A local chat backend must already be running for chat/extraction jobs. Collection import accepts an explicit local folder; it is not an arbitrary file-upload endpoint. Mission creation defaults to unarmed Observe mode, with 1–100 steps. Arming is explicit; stopped or uncertain missions require native mission review/resume. Once armed, missions follow the existing independent supervisor lifecycle; closing only the API is not an undo operation. The Workspace Stop control uses the existing mission pause boundary after this runtime arms a mission.

Chat responses, structured extraction and collection sync return a job ID. Up to four jobs and eight HTTP requests may run concurrently. Jobs have a ten-minute deadline; model calls have a shorter transport deadline. Cancellation never rolls back already completed effects. After a crash, saved queued/running API jobs become `needs_review`, not automatically replayed. Saved chats, tokens, receipts, jobs and artifact revisions are account-private and encrypted by the existing sealed-profile system. Atomic publication cannot guarantee durability against physical media failure or abrupt removal before storage flush; retained receipts prevent blind retry when outcomes are uncertain.

Lists default to 50 items, with `offset` and `limit` (maximum 200). Output downloads return base64 chunks up to 1 MiB; retain the returned `identity` for subsequent chunks and stop if the file changes. Requests/results are bounded at 2 MiB. The OpenAPI file describes exact fields and query parameters. Error examples: `UNAUTHORIZED`, `SCOPE_REQUIRED`, `IDEMPOTENCY_CONFLICT`, `NEEDS_REVIEW`, `OUTPUT_CHANGED`, `INVALID_ARGUMENT`. No automatic cleanup removes old receipts; the 10,000-receipt ceiling fails visibly for review.

SDKs and examples are individual source files:

- [Python standard-library client](../SDK/python/portalai.py) and [chat example](../SDK/examples/chat.py). Run the example using this SSD's `Runtime/BootstrapPython/python.exe`, supplying the live API URL; it prompts for the token.
- [TypeScript fetch client](../SDK/typescript/portalai.ts) and [artifact example](../SDK/examples/artifact.ts). Compile in your application's TypeScript toolchain. No Node installation is required by PortalAI itself; its tests use the already bundled Node executable.
- [OpenAPI 3.1 contract](../SDK/openapi.json). Compatible additions stay within v1; incompatible contract changes require a new major route.

Source: [HTTP/auth/receipt boundary](../Agent/application_api.py), [resource adapters](../ControlCenter/application_api_runtime.py), [request contracts](../ControlCenter/application_api_contract.py), [native controls](../ControlCenter/workspace_integration_ui.py).

## Interactive artifacts

In **Workspace → Artifacts**, edit HTML, SVG or chart JSON. **Save as new** creates an artifact; **Save revision** requires the current head revision and refuses an edit based on an outdated head. Earlier revisions remain immutable. Load a revision, compare it with the head, or restore it as a new revision. Export writes the selected original source to private `Outputs/Artifacts/{artifact}/{revision}`. A modified existing export is preserved and causes a conflict. Limits are 512 KiB per source and 256 revisions per artifact. Model-created artifacts use the `artifact` chat tool; creating/saving content never executes it.

Chart example:

```json
{"title":"Readings","labels":["Monday","Tuesday"],"series":[{"name":"Temperature","values":[21,24]}],"style":"line"}
```

Charts support line/bar style, 1–1,000 labels, 1–16 finite numeric series, series toggles and point hover. HTML supports inline JavaScript and styles. SVG can be edited as source. Use **Preview editor** explicitly to open the bundled Chromium browser. The browser has its OS sandbox enabled and an opaque-origin iframe with only `allow-scripts`: no app bindings, same-origin privilege, forms, downloads, popups, external frames or network access. Content Security Policy and browser request blocking reinforce those restrictions. Preview supports inline/data assets rather than remote CDNs. It closes on Stop, Workspace close, ended login, parent exit, or after 30 minutes. This is browser isolation, not a VM or a guarantee against browser vulnerabilities. Exported source is the original file; opening it outside PortalAI does not carry PortalAI's preview restrictions.

Source: [revision store](../Agent/artifacts.py), [preview document/CSP/chart renderer](../Agent/artifact_document.py), [owned browser worker](../Agent/artifact_preview_worker.py), [process ownership](../ControlCenter/artifact_preview.py). Browser semantics: [MDN iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe).

## Verification and distribution

Automated coverage is in [test_integration.py](../Maintenance/Tests/test_integration.py), [encrypted-profile tests](../Maintenance/Tests/test_integration_profiles.py), and [live acceptance smoke](../Tools/smoke_integration.py). The smoke has browser, owned-worker, UI and CPU-model components, with synthetic data only. Installed-run evidence lives under `Maintenance/Validation/Integration-20261029` on each SSD. Windows results do not establish physical Linux/macOS or surprise USB-removal behavior.

The offline Integration kit requires the previously installed Workspace patch and its bundled dependencies. Each SSD has its own source, guarded update manifest and rollback journal under `Utilities/Integration-20261029`; it never needs the other SSD or a C: development checkout. Current individual source files and SDKs are published in both GitHub editions. Historical r51 download archives are not rebuilt by this source patch. Python-runtime and NumPy consolidation are explicitly outside this patch.
