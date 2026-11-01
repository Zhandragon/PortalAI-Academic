# Portable capabilities — Windows r58

This update adds roughly 6 MB of application files to each independent installation. It installs no model weights, Python environment, Node environment, service or background watcher. The existing SSD free-space reserves still apply. Browser libraries load only for the corresponding artifact preview; they do not load when Chat opens. The application keeps the existing main pages and compact layouts.

## Projects and importable skills

Open **Chat > Workspace > Projects** to create a project, add shared instructions and knowledge collection IDs, and assign existing chats or create a new chat. Project removal preserves conversations and documents. Instructions affect future turns; they do not rewrite saved messages or override account permissions. Collections guide retrieval, rather than granting access to a different account's data. Limits: 128 projects, 4,000 instruction characters and 16 collections per project.

**Workspace > Skills** imports a single Markdown/text guide. Review it, then choose **Save and enable**. Nice receives a small catalog and uses `skill list/read` to page in relevant instructions only when needed. Importing does not enable execution, install packages or grant permissions. A guide can have simple `name` and `description` frontmatter. Script bundles, ZIP packs and package dependencies are deliberately unsupported. Limit: 128 guides of 32 KiB each (about 4 MiB total before profile encryption and backups).

Source: [portable_workspace.py](../Agent/portable_workspace.py), [native management](../ControlCenter/portable_workspace_ui.py), [tool adapter](../ControlCenter/capability_tools.py).

## MCP sign-in, resources and prompts

In **Workspace > Connections**, select an HTTP connection, configure OAuth with its trusted issuer, public/native client ID and requested scope, and explicitly sign in. The native flow uses discovery, PKCE S256, state validation, a loopback callback, resource-bound tokens and no client secret. A provider can use an ephemeral callback port or a registered fixed port with path `/portalai-oauth/callback`. Credentials stay in the current account's existing encrypted profile. Sign-out removes local credentials; it does not claim to revoke the provider's grant.

This is a preregistered public-client flow, not universal OAuth compatibility. Dynamic client registration, client-ID metadata documents and arbitrary challenge-provided discovery URLs are not implemented. Providers requiring those need a compatible registered client or the existing static-token connection. HTTPS is required except for explicit local loopback test providers. Real provider accounts were not used in validation.

Resources and prompts have a separate explicit content grant. Nice can list them and request only advertised URIs/names. Long content is paged. Returned content remains untrusted evidence; it does not enable tools or approve actions. Tool grants and durable effect receipts remain separate. Credential refresh occurs before dispatch, never by silently retrying an uncertain tool action.

Source: [mcp_oauth.py](../Agent/mcp_oauth.py), [mcp_client.py](../Agent/mcp_client.py), [connection UI](../ControlCenter/mcp_workspace_ui.py).

## Workflow editor and API execution

**Workspace > Workflows > Visual step editor** provides ordered native forms for prompts, knowledge, approved MCP calls, PortalAI tools, conditions, approval points and output. `@inputs.name` and `@steps.name` reference values; a leading `=` supplies JSON. Apply edits before switching steps. **Use this workflow** validates the draft and returns it to the existing JSON editor; **Save** publishes it. Editing never runs steps. The engine remains bounded to forward conditions and explicit human approvals; this is an ordered editor, not a freeform node canvas.

The application API adds `workflows:read` and `workflows:execute` scopes and these routes under `/v1`: `GET /workflows`, `GET /workflows/{id}`, `POST /workflows/{id}/runs` with `inputs`, `GET /workflow-runs/{id}`, and `POST /workflow-runs/{id}/continue`. Mutations require an idempotency key. Returned jobs expose progress/results through existing job routes. Approvals and uncertain effects must be reviewed in the native Workspace. A known pre-execution refusal is recorded as rejected; an interrupted effect remains pending and cannot be bypassed by changing keys. Ordinary API chat remains text-only; tool execution is through reviewed workflows, not an unrestricted remote Nice session.

Source: [workflow_builder.py](../ControlCenter/workflow_builder.py), [workflows.py](../Agent/workflows.py), [application_api_runtime.py](../ControlCenter/application_api_runtime.py), [application_api.py](../Agent/application_api.py).

## Voice interruption and optional streaming

While Nice is speaking, click/tap the orb or press Enter when it has focus to stop only that spoken reply. Full Stop still cancels the active operation. Normal transcript text is retained.

Voice settings add two opt-in controls. **Allow spoken interruption (use headphones)** listens during playback and retains the next utterance after stopping speech. It has no acoustic echo cancellation: speakers can retrigger the microphone, so use headphones or leave this off. **Stream completed sentences with Piper when RAM permits** speaks bounded completed sentences while text arrives. It is disabled when spoken interruption is enabled. It may speak a partial answer before generation finishes. If the memory check rejects concurrent Piper, the remaining reply uses ordinary voice admission after text generation.

Qwen uses the existing text-then-voice memory handoff, not streaming generation. Its approved voice direction and pitch are unchanged. Both playback paths retain the 500 ms silent lead-in and 350 ms tail. The settled orb stays still. No new speech model, resident microphone service or echo-cancellation library is added.

Source: [chat_voice.py](../ControlCenter/chat_voice.py), [native_chat.py](../ControlCenter/native_chat.py), [voice_visualizer.py](../ControlCenter/voice_visualizer.py).

## Idle knowledge refresh and model comparison

Select a collection in **Workspace > Knowledge** and choose 5 minutes, 15 minutes or hourly refresh. It is off by default, runs only while Workspace is open and idle, and pauses for chat/hands-free activity, low available RAM or storage admission failure. Closing Workspace or Stop cancels its work. Unchanged sources do not load the embedding model or rewrite the index. Changed-source copies have a cumulative 32 MiB automatic allowance per collection; after that, review and explicitly sync. Existing manual import limits and retained versions still apply. There is no filesystem daemon.

**Workspace > Compare** runs one prompt across two or three effort profiles sequentially, saves each result, and attempts to restore the saved chat profile. No extra models are downloaded. Manual model overrides are respected, so profiles can select the same model; results show the actual model IDs. Stop/account changes prevent automatic model restoration. No tools or chat history are sent. Partial results survive failure; unfinished runs are never replayed. The archive is bounded to 100 runs and prompts to 4,000 characters. Sequential execution avoids keeping multiple LLMs in memory.

Source: [knowledge_base.py](../Agent/knowledge_base.py), [workspace_panel.py](../ControlCenter/workspace_panel.py), [model_comparison.py](../ControlCenter/model_comparison.py).

## Offline rich artifacts and desktop targeting

**Workspace > Artifacts** now previews and exports Markdown, Mermaid and React JSX, alongside existing HTML/SVG/charts. React supports a default component or `App` and bundled React/ReactDOM imports; external packages and network access are unavailable. Mermaid uses strict security and bounded graph size. Markdown is sanitized. Existing isolated browser previews, revision checks and account boundaries remain. Previews are user-opened browser windows, not an always-resident chat side panel.

Bundled pinned renderers total about 5.9 MB: Mermaid tiny, Babel standalone, React/ReactDOM, scheduler, marked and DOMPurify. Their adjacent license files and `ControlCenter/ArtifactAssets/manifest.json` list upstream package versions, archive integrity, extracted members and SHA-256 hashes. `tools/build_artifact_assets.py` in the source repository reproduces extraction without installing npm. The preview verifies local asset hashes before use. User-created artifacts and browser working RAM are additional, not part of the installed-file estimate.

The `computer` tool adds `elements` and `click_element` for Windows accessibility targets, plus bounded `drag`. These retain explicit per-window permission, screenshot/vision requirements, expiring single-action observations, foreground/occlusion checks and Stop revocation. Accessibility reads are bounded and run in a timed owned Windows helper; password fields and value patterns are excluded. A target is revalidated before clicking, and a drag releases its button on interruption. Apps that do not expose useful accessibility controls still use screenshots. The 9 KiB helper uses Windows' existing .NET Framework and is shipped with source, a hash manifest and `tools/build_accessibility_helper.py`; it does not change PowerShell execution policy. No always-running UI service is installed.

Source: [rich_artifacts.py](../Agent/rich_artifacts.py), [artifact preview](../Agent/artifact_preview_worker.py), [desktop_accessibility.py](../Agent/desktop_accessibility.py), [accessibility helper source](../Tools/AccessibilitySnapshot.cs), [desktop_control.py](../Agent/desktop_control.py).

## Storage and validation

Projects, enabled skills, MCP credentials, comparisons and workflow receipts use the current account's portable storage and existing encryption/sealing rules. D: and E: keep independent copies. The deprecated C: installation is not involved. Installer archives, validation fixtures and recovery snapshots consume separate build/recovery storage; they are not counted as installed feature bytes. Automatic refresh is capped because retained document revisions can otherwise grow over time. No owner documents, profiles, models or runtime distributions are removed.

Regression source: [test_portable_capabilities.py](../Maintenance/Tests/test_portable_capabilities.py), [API tests](../Maintenance/Tests/test_integration.py), [profile isolation](../Maintenance/Tests/test_workspace_profiles.py). Release validation distinguishes mocked boundary tests, native/browser smoke tests and untested real-provider or physical-device cases. Exit and reopen PortalAI normally after updating. Windows is r58; Linux/Mac remain r51.
