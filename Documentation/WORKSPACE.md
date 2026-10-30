# Workspace: knowledge, MCP, workflows and computer control

This source patch adds one native **Workspace** sheet. Open it from Chat's attachment controls or the launcher menu. The eleven primary pages and six Controls buttons are retained. Sign in first. Connections, workflow execution and computer access require an administrator account; document collections belong to the signed-in profile.

## Local document knowledge

1. Open **Workspace → Knowledge**, name a collection and choose its source folder.
2. Choose **Add collection**, select it, then **Sync selected**. Sync is explicit; no filesystem watcher or background service is installed.
3. Search in the sheet or ask chat to use the `knowledge` tool. A selected collection restricts the sheet's search; without a selection it searches all collections.
4. Answers should cite the returned file, location and `kb:` citation. `knowledge(action="read", citation=...)` retrieves the exact indexed excerpt and the private source snapshot reference.

Supported formats: UTF-8 text/Markdown/CSV/TSV/JSON/XML/HTML, DOCX, XLSX, PPTX, PDF, PNG, JPEG, TIFF and BMP. PDF citations identify actual PDF pages; PowerPoint citations follow presentation order; spreadsheets identify sheets. DOCX citations say **document**, because this extractor does not render Word pagination. Legacy binary DOC/XLS/PPT and password-protected documents are not supported. Spreadsheets use saved values; they do not execute formulas.

PDF text is extracted locally. Pages with very little embedded text and image files use bundled RapidOCR. OCR can misread scans. Search combines SQLite FTS5 keyword ranking with local 384-dimensional MiniLM embeddings using reciprocal-rank fusion. The embedding model is primarily English; relevance and OCR accuracy are not evidence that a retrieved claim is true.

Sync hashes source files, extracts only changed documents and builds a replacement SQLite index before publishing it. A failed sync leaves the previous index available. An unavailable source folder is not treated as an empty folder. Removed source files leave the current index only after a successful inventory. Versioned citation IDs reject references to text replaced by a later sync. Source snapshots are retained for review; they are not silently pruned.

Limits per collection: 5,000 files, 1 GiB of input, 100 MiB per file and 50,000 chunks. A PDF is limited to 1,000 pages; extraction and Office decompression have separate bounds. Search returns at most 20 excerpts. Explicit limits fail visibly rather than silently marking a partial index complete.

Collections, indexes and copied originals live in account-private `Data/Knowledge`. They participate in encrypted profile sealing. Login restores their contents lazily; listing collections does not decrypt their indexes. An ended login invalidates existing knowledge objects. Source paths on the same SSD are saved relative to its drive root, so changing the drive letter does not break them; external source folders must remain available for future syncs. Copied documents and indexes remain searchable without the original folder.

## Standard MCP tool connections

Open **Workspace → Connections**. Create a disabled connection, discover its tools, select the individual tools to grant, then choose **Approve selected tools**. Discovery starts a stdio server or contacts the HTTP endpoint. It is an explicit administrator action, not an automatic search for installed programs.

Examples of the configuration JSON:

```json
{"transport":"stdio","command":["{python}","{root}/Tools/my_mcp_server.py"],"env":{}}
```

```json
{"transport":"http","url":"https://example.org/mcp","headers":{"Authorization":"Bearer YOUR_TOKEN"}}
```

The stdio executable must be `{python}` or a path relative to this portable root. `{root}` may appear in arguments. A packaged Node server can use the bundled Playwright Node executable at `Runtime/Web/windows-x64/packages/playwright/driver/node.exe`; its JavaScript packages must also travel with the SSD. PortalAI does not invoke `npx`, install arbitrary servers automatically or require host Node/Python.

Supported protocol subset: initialization/version negotiation, initialized notification, paginated tool discovery and tool calls over newline-delimited stdio or Streamable HTTP with JSON/SSE responses. HTTP requires HTTPS except on loopback. Session and protocol headers are retained. There is no legacy HTTP+SSE transport, OAuth login flow, resources/prompts browser, sampling, elicitation, resumable event replay or subscription support. Unsupported server-to-client requests receive a protocol error; ping is supported. These are tools-client capabilities, not a claim of every MCP feature.

Each tool grant stores its approved input schema. Calls validate arguments, refuse external schema references and rediscover the current schema before dispatch. A changed schema or revoked grant requires renewed approval. Tool annotations do not grant trust. Server output and descriptions remain untrusted input.

Connection configuration and credentials live in encrypted account-private `Data/Connections`. Catalogues omit secret headers and environment values. Stdio children receive a small portable environment, not profile keys or login capabilities. They run as the current OS user under owned process cleanup; this is **not an OS sandbox**. Only configure servers you intend to run with that access.

A durable pending receipt is written before every tool dispatch. Complete receipts can satisfy the same workflow operation ID without executing it again. A crash, timeout or lost response leaves an uncertain receipt and blocks identical calls until the user reviews the external outcome. **Uncertain calls → Confirm completed** records completion without another dispatch. **Allow one reviewed retry** permits another attempt; it does not itself execute anything. No network or stdio tool call is automatically retried. This reduces duplicates; it cannot provide universal exactly-once execution for an arbitrary external service.

## Reusable workflows

Open **Workspace → Workflows**. The editor starts with a complete example: knowledge search → local-model draft → human approval → output. Save it, select it and supply its named inputs as JSON. The native editor exposes the full versioned definition rather than hiding executable code in a prompt.

Step kinds:

| Kind | Behavior |
| --- | --- |
| `knowledge` | Search/read saved collections with ordinary knowledge arguments. |
| `prompt` | Ask the currently running local chat model a bounded question with source context; no tools in this step. Start chat first if the model is offline. |
| `mcp` | Call an approved connection/tool with explicit arguments and a stable run/step operation ID. |
| `tool` | Call a listed PortalAI file, science, browser or media tool through its existing account policy. Shell and recursive workflow calls are excluded. |
| `condition` | `equals`, `not_equals`, `contains` or `truthy`; branch forward to a step ID or `end`. |
| `approval` | Pause until the user approves that step in the sheet. The model cannot approve it. |
| `output` | Return a literal or referenced value. |

`{"$ref":"inputs.question"}` and `{"$ref":"steps.search.results.0.text"}` are typed data references, not Python or shell interpolation. Inputs must match the template's declared fields. Templates have at most 64 steps, no backward edges and no implicit loops. Each step gets at most three explicit attempts; a run yields after ten minutes. Individual tool/model deadlines still apply.

Every run stores an immutable template snapshot, inputs, results, attempts, cursor and approval/review history in private `Data/Workflows`. Editing a template does not alter a run already created from it. Completed steps are not replayed when reopening a run. Only **Continue** (or the chat tool's `continue`) advances it; this feature does not silently arm missions, schedule services or resume tasks at login.

External tools receive a write-ahead pending step. If interrupted, inspect the saved run and the real external state. Confirm the actual result or explicitly allow a retry. An MCP step may also have an uncertain MCP receipt, which must be reviewed separately. Approving a waiting step or resolving uncertainty does not automatically execute the next step. This is deliberate, inspectable recovery, not a promise that a crash can undo effects.

## Local computer control

This adapter currently supports **Windows only**. Linux/macOS source trees contain the shared integration, but native control is unavailable there.

1. Select a local model with a vision projector, such as an installed Qwen3-VL model. A text-only model is refused for screenshots/input. Larger context helps accommodate tools and screenshots.
2. Open **Workspace → Computer → Refresh windows** and explicitly allow the target window for this login.
3. Return to chat and give a scoped task. The `computer` tool enumerates windows, captures the allowed window, then accepts clicks, double clicks, pointer movement, scrolling, Unicode typing, key chords, focus, maximize, minimize and restore.
4. Each input consumes one fresh screenshot token and returns a new screenshot. Coordinates refer to that bounded image. A moved/resized window, changed focus, covered click point, stale token, ended login or revoked permission refuses input.

**Stop**, **Revoke all**, or **Ctrl+Alt+Pause** revokes computer access. Holding Escape before an action also stops it. Grants are in memory, tied to the window's process identity and current login; they do not survive restart. The emergency key monitor runs only while access is granted. Windows may refuse foreground activation; bring the allowed window forward rather than assuming a click went to it. Protected/elevated desktops and UAC are not bypassed.

Screenshots are captured from the target window, reduced to at most 1024×768 and kept only in memory. The latest valid observation in the current user turn is attached as image input to the local vision request, with a separate context reservation. Screenshot bytes are not placed in ordinary chat transcripts. Stop, revocation or expiry removes their availability. A single observed image is not a complete accessibility tree. Native accessibility-element selection, drag gestures and cross-platform adapters are not implemented in this release.

This implements the screenshot → model → action → screenshot loop. It does not copy ChatGPT's proprietary tool server or promise its model accuracy. Window grants are application controls, not OS isolation. A local model can still choose a wrong UI action; use a narrow task and verify the result. Tests of native input and tests of model perception are recorded separately.

## Portable packaging and source

The active Windows installs use `Runtime/Knowledge` for extraction/OCR/schema libraries and a 23 MB quantized MiniLM model. NumPy/ONNX Runtime from Piper and Pillow from Science are reused. No Torch, SentenceTransformers framework, vector database service, Docker image or host interpreter is added for these features. All model inference and OCR are local; HTTP MCP connections contact the configured service by design.

For a source recipient missing the runtime, stop PortalAI and run its bundled Python with `Tools/install_workspace_runtime.py`. It selects compatible pinned wheels, verifies size/SHA-256, and publishes only a completed new `Runtime/Knowledge` directory. Existing installations are refused rather than overwritten. `Agent/workspace_assets.json` records immutable model revision, hashes, wheel versions and URLs. New local update kits carry the ready Windows runtime for offline use. Existing r51 clean-installer archives remain historical artifacts; do not assume they contain this later source patch.

Source entry points (individually browsable on GitHub):

- [Knowledge store](../ApplicationSources/Windows/PortalAI/Agent/knowledge_base.py), [extraction/OCR](../ApplicationSources/Windows/PortalAI/Agent/knowledge_extract.py), [embeddings](../ApplicationSources/Windows/PortalAI/Agent/knowledge_embeddings.py).
- [MCP client and receipt journal](../ApplicationSources/Windows/PortalAI/Agent/mcp_client.py), [owned stdio launch gate](../ApplicationSources/Windows/PortalAI/Agent/mcp_launch.py).
- [Workflow engine](../ApplicationSources/Windows/PortalAI/Agent/workflows.py), [account-scoped storage](../ApplicationSources/Windows/PortalAI/Agent/workspace_store.py).
- [Native desktop controller](../ApplicationSources/Windows/PortalAI/Agent/desktop_control.py), [chat tool and image adapters](../ApplicationSources/Windows/PortalAI/ControlCenter/capability_tools.py), [native Workspace sheet](../ApplicationSources/Windows/PortalAI/ControlCenter/workspace_panel.py).
- [Runtime installer](../ApplicationSources/Windows/PortalAI/Tools/install_workspace_runtime.py), [asset lock](../ApplicationSources/Windows/PortalAI/Agent/workspace_assets.json), [read-only source bloat auditor](../ApplicationSources/Windows/PortalAI/Tools/audit_source_bloat.py).
- [Recovery/protocol tests](../ApplicationSources/Windows/PortalAI/Maintenance/Tests/test_workspace.py), [encrypted-profile tests](../ApplicationSources/Windows/PortalAI/Maintenance/Tests/test_workspace_profiles.py), [real extraction/MCP/UI smoke](../ApplicationSources/Windows/PortalAI/Tools/smoke_workspace.py), [native input smoke](../ApplicationSources/Windows/PortalAI/Tools/smoke_computer.py), [local vision smoke](../ApplicationSources/Windows/PortalAI/Tools/smoke_workspace_vision.py).

Shared code is published in Full and Academic Windows/Linux/macOS trees. Academic model-selection policy and existing platform ownership code remain in place. Windows execution tests do not establish native Linux/macOS acceptance, physical USB-removal durability, every OCR language, high-DPI/multi-monitor input accuracy or arbitrary third-party MCP compatibility.

## Recorded acceptance evidence

The 2026-10-29 Windows acceptance run passed 29 focused protocol, recovery, encrypted-profile and computer authorization/image-lifetime tests. Real smoke tests exercised quantized MiniLM retrieval, PNG/scanned-PDF OCR with page citations, incremental reopen, stdio MCP startup/call/cleanup and cancellation, and all four native Workspace tabs in light/dark/narrow layouts. Synthetic desktop tests verified real mouse/Unicode keyboard input, stale-observation refusal, maximize/restore and revocation. A separate CPU Qwen3-VL-2B vision test correctly read all four tab names from a synthetic screenshot (29.72 seconds, 1,083 prompt tokens). Native input and model perception were tested separately; this is not evidence of a model completing an arbitrary desktop task autonomously.

Evidence is under `Maintenance/Validation/Capabilities-20261029` on the portable SSDs. Tests use synthetic fixtures; they do not resume owner missions. Source-only broad checks initially failed where the checkout lacked bundled runtime paths; installed-runtime validation is recorded separately. The runtime installer omits unused generated CLI launchers that embed build-drive paths. The offline SSD update kits use the existing guarded updater with hashes, prior-file backups, interrupted-update recovery and rollback.

Upstream references: [MCP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), [OpenAI computer-use loop](https://developers.openai.com/api/docs/guides/tools-computer-use).

## Structured output, API and artifacts

The Workspace sheet now also includes Structured, API and Artifacts tabs. See [the integration guide](INTEGRATION.md) for usage, exact API/SDK source, lifecycle, limits and validation. The Python distribution assessment is [read-only](PYTHON-DISTRIBUTION-AUDIT-20261029.md); NumPy and runtime merging remain out of scope.
