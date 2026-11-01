# Windows r59: portable intelligence and hands-free improvements

This release extends r58 using the runtimes and models already on the SSD. D: and E: remain independent full installations. The deprecated C: installation is excluded. Linux and Mac remain at their existing release. Exit and reopen PortalAI normally after updating.

## What is available

| Capability | Where to use it | Original source |
| --- | --- | --- |
| Skill guides, supporting files and isolated Python wheels | Workspace → Skills → Import; review files, enable the guide, then separately grant script execution | [skill_packs.py](../Agent/skill_packs.py), [portable_workspace_ui.py](../ControlCenter/portable_workspace_ui.py) |
| MCP OAuth discovery, public dynamic registration and client metadata documents | Workspace → Connections → OAuth client mode | [mcp_oauth.py](../Agent/mcp_oauth.py) |
| Draggable workflow nodes and forward links | Workspace → Workflows → Visual step editor | [workflow_canvas.py](../ControlCenter/workflow_canvas.py), [workflows.py](../Agent/workflows.py) |
| Background collection monitoring | Enable a collection's existing refresh interval; the monitor runs while signed in and yields to chat/hands-free | [knowledge_monitor.py](../ControlCenter/knowledge_monitor.py) |
| Installed-model comparisons and bounded peer review | Workspace → Compare → List installed models; choose two or three IDs and one to three rounds | [model_comparison.py](../ControlCenter/model_comparison.py), [comparison_workers.py](../ControlCenter/comparison_workers.py), [model_compare_worker.py](../Agent/model_compare_worker.py) |
| Embedded offline artifacts and reviewed React libraries | Workspace → Artifacts → Preview editor / Review libraries | [artifact_preview.py](../ControlCenter/artifact_preview.py), [artifact_embed.py](../Agent/artifact_embed.py), [artifact_libraries.py](../Agent/artifact_libraries.py) |
| Tool-enabled Nice API conversations | Workspace → API; issue `agent:execute` and individual tool grants, then POST `/v1/chats/{id}/agent` | [headless_chat.py](../ControlCenter/headless_chat.py), [application_api_runtime.py](../ControlCenter/application_api_runtime.py) |
| Evidence-linked task plans | Nice's `task` tool; load its exact schema through progressive tool discovery | [task_notebook.py](../ControlCenter/task_notebook.py) |
| Relevant skill discovery and reusable lesson drafts | Relevant enabled skill descriptions enter the small discovery catalogue; Workspace → Skills can draft a disabled lesson from a fully verified task plan | [portable_workspace.py](../Agent/portable_workspace.py), [portable_workspace_ui.py](../ControlCenter/portable_workspace_ui.py) |

Comparisons have no tools, credentials or GUI chat history. Later rounds review earlier answers as unverified suggestions. They do not certify correctness. Ordinary chat starts no extra models or critique rounds. Task verification links original successful tool-message IDs and hashes; a successful tool return does not itself prove that an acceptance criterion was satisfied. Lesson drafts require human review and enabling.

## Voice: streaming, interruption and loading

The approved Nice voice direction and **−0.5 semitone** adjustment remain. Both playback paths preserve the **500 ms silent lead-in and 350 ms silent tail** that fixed clipped openings/endings. The text reply stays visible in chat, including compact chat-expanded mode.

Qwen now emits decoded audio chunks while generating. It still waits for the LLM turn to finish and release its VRAM. A single continuous player consumes those chunks; it does not restart the audio device for every chunk. Bounded queues and disk backpressure prevent a long reply from accumulating unlimited audio.

On Windows CUDA machines with at least 16 GiB total RAM and 8 GiB currently free, hands-free can import Qwen's Python packages while listening. This loads no model weights. The preparatory worker has a 2 GiB memory ceiling, expires after two minutes, and closes on Stop, sign-out or low RAM. It is used once and exits after speech. Fresh RAM/VRAM admission still happens after the owned LLM handoff. Smaller machines skip preparation; Fast effort keeps the existing lightweight Piper selection. Explicit voice choices remain respected.

Windows speaker echo cancellation uses the default output-device reference and the selected microphone through the built-in Voice Capture DSP. This is optional in Chat Preferences. It does not change Windows sound settings. Room acoustics, microphone position and output routing still affect quality; headphones remain useful. With interruption enabled, the next utterance is retained while playback stops. Transcription and the next turn wait for the current model/tool turn to finish, so interrupting speech never retries an in-flight tool action. Piper sentence streaming and interruption can now be combined.

Voice implementation: [incremental codec decoding](../Agent/qwen_voice_stream.py), [continuous PCM player](../ControlCenter/voice_pcm_player.py), [bounded import preparation](../Agent/voice_prewarm.py), [voice orchestration](../ControlCenter/chat_voice.py), [AEC wrapper](../ControlCenter/voice_echo.py), [original C++ helper source](../Tools/VoiceEchoCapture.cpp), [binary integrity manifest](../Tools/voice_echo_capture.json). The helper is 168,448 bytes and uses the Windows SDK/DSP already on Windows; no additional voice model or runtime is downloaded. The repository includes `tools/build_voice_echo_helper.py` for rebuilding it with an installed MSVC/Windows SDK toolchain.

## Small, reviewed bundles

A skill ZIP contains `skill.json`, `SKILL.md` and supporting files. Version 1 of the manifest uses:

```json
{"version":1,"instructions":"SKILL.md","files":{"SKILL.md":"<sha256>","scripts/report.py":"<sha256>","vendor/helper.whl":"<sha256>"},"scripts":{"report":"scripts/report.py"},"wheels":["vendor/helper.whl"]}
```

Every payload file must be hashed. Limits are 128 MiB compressed, 256 MiB expanded including unpacked wheels, 2,048 files and 32 scripts/wheels. Wheels must be compatible pure-Python or CPython 3.12 Windows x64 builds. Supply the required transitive wheels; there is no online dependency resolver, source build or installer hook. Executable `.pth` hooks are refused. Dependencies are private to the pack, never merged into PortalAI's Python installation. Scripts require both the administrator role and a separate reviewed grant, run in an owned process with time/output/memory bounds, and are **not an OS security sandbox**. An uncertain execution receipt blocks identical automatic replay until human review.

An artifact library ZIP contains `library.json` and already bundled UTF-8 CommonJS JavaScript:

```json
{"version":1,"name":"My chart helper","modules":[{"name":"chart-helper","file":"chart-helper.js","sha256":"<sha256>"}]}
```

Import leaves the library disabled. Inspect its manifest/source and enable it in Workspace before selecting its ID in a React artifact. Up to eight libraries may be pinned to a revision, with 16 MiB combined source and 8 MiB per module. React/ReactDOM cannot be replaced. Modules may require other reviewed modules, including circular imports; unresolved names produce a visible error. This supports pre-bundled CommonJS, not arbitrary npm installation or Node APIs.

The existing Chromium runtime is opened only for preview. Code runs in an opaque-origin scripts-only iframe with network, downloads, service workers, host bindings and parent-document access blocked. Disabling a library blocks subsequent previews/exports; close an already running preview to stop it immediately. Artifact revisions retain dependency hashes, restore preserves them, and exporting a dependency-bearing React artifact creates a standalone offline HTML preview containing the reviewed libraries. The normal source-only export remains for artifacts without libraries. Separate preview remains available if a display/DPI setup cannot embed Chromium.

## API grants and recovery

Ordinary `/messages` chat retains its existing text-only behavior. `/agent` uses the same NativeChat harness, progressive tool schemas, context admission, checkpointing and execution receipts as Nice. Each token must separately include `agent:execute` and its allowed tool names. A request can narrow those names, never expand them. The account's existing role and tool checks still apply. No unrelated GUI chat memory is imported. Revoking a token or pressing Stop cancels its work at cancellation checks.

Python SDK example (the TypeScript SDK also has `agent`):

```python
job = client.agent(chat_id, "Read the supplied local report and summarize it.",
                   tools=["read_file"], max_tool_calls=6, key=stable_request_key)
result = client.wait(job["job_id"])
```

Keep the same idempotency key when checking an uncertain submission. Completed tool results and execution metadata are saved in the API conversation. An unfinished agent turn is marked `needs_review` and is never replayed automatically. Inspect its saved receipts before deliberately starting another conversation. This release does not automatically resolve unknown external side effects or sign in to third-party providers.

## Memory, storage and latency bounds

[storage_reserve.json](../Agent/storage_reserve.json) raises the application admission floor to **80 GiB free per SSD** (85,899,345,920 bytes, stricter than 80 decimal GB). Existing larger reserves still win. This is an application preflight, not an operating-system disk quota: user file copies, external applications and uncontrolled external tool writes can consume space independently. Installers, recovery copies and user outputs are accounted separately from application source growth.

Parallel comparison is opt-in and capped at two fully GPU-offloaded models. Admission requires a dedicated GPU, at least six logical CPU cores, combined model estimates plus 3 GiB free VRAM and 4 GiB free RAM; each launch rechecks available memory. Otherwise comparisons run sequentially. CPU thread counts, context, output tokens, response/startup time and total rounds are bounded. Owned worker jobs/ports are closed after the run; the prior chat model is restored unless Stop or a newer operation prevents it.

Background indexing uses Windows folder-change signals and the selected 5/15/60-minute interval. It defers during chat/hands-free, respects RAM/storage reserves and keeps no embedding model permanently resident. The GUI's workflow drag redraw is throttled; browser rendering, bundle import and model work run outside the Tk event thread. No always-running system service, new Python tree, new browser runtime or new model weights are added.

Measured on the development RTX 3090 machine, not a guarantee for other computers:

- Qwen first chunk: approximately 52 seconds cold, 21–26 seconds on repeat standalone workers, and **8 seconds with completed import preparation**. The prepared worker used about 742 MiB working RAM / 1.03 GiB private memory before model loading. The user confirmed the actual streamed reply was complete and smooth.
- Speaker interruption: actual AEC capture transcribed “Nice stop speaking” and interrupted the approved audio. This validates one microphone/speaker setup, not every acoustic environment.
- Two installed models (1.7B and 4B), two comparison rounds: about **14 seconds total including loading** after reusing the admitted workers between rounds (the initial reload-per-round version took 31 seconds). Both parallel rounds passed combined admission; the workers closed before chat restoration.
- Real 1.7B API tool request: approximately **6 seconds including loading**, progressive tool discovery and the actual file read.
- Disposable GUI: 4,573 timer samples; 95th-percentile callback lateness approximately **12 ms**. The largest observed delay was 824 ms during the run that included resizing and UI automation; this is not a promise of a fixed frame rate.

Tests cover bounded bundles, tampering, review grants, pending-effect replay refusal, OAuth protocol discovery/registration, task evidence, forward workflow routing, folder notifications, combined model admission, API grants/revocation and existing voice/context/lifecycle behavior. Real Chromium validated reviewed-library interaction and isolation; native GUI inspection validated embedding, resize, clicks and workflow dragging. Provider OAuth used synthetic responses rather than a real account sign-in. Full fresh recipient installation and other physical hardware tiers are not represented by the local measurements. Exact packaged/drive test counts and hashes are published with the release validation report.
