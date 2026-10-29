# PortalAI source map

[Mission recovery contract](MISSION-RECOVERY.md) · [Every application module](MODULE-INDEX.md) ·
[Paths, hashes and Python symbols](SOURCE-INVENTORY.json) · [Audit and limitations](SOURCE-AUDIT-20261029.md)

The application is published as individual source files under `ApplicationSources`.
Choose the platform and edition you are inspecting. `InstallerSources` contains
installer engines and launchers. `Utilities` contains companion programs, source
handoffs and historical evidence; a `before` or evaluation fixture is not the live
implementation. Release archives and pinned upstream downloads supply large
runtimes, third-party packages, model weights and artwork separately.

## Start from the capability

Paths below use the Windows tree as an entry point. Use the corresponding Mac or
Linux tree for platform-specific behavior; Windows test results do not establish
native acceptance on another OS.

| Capability | Code and responsibility |
| --- | --- |
| Persistent missions | [mission_runner.py](../ApplicationSources/Windows/PortalAI/Agent/mission_runner.py): mission state, planning, execution and write-ahead checkpoints. [mission_supervisor.py](../ApplicationSources/Windows/PortalAI/Agent/mission_supervisor.py): arming, process ownership, timeout, reconciliation and retry. |
| Schedules and adaptive recovery | [mission_schedule.py](../ApplicationSources/Windows/PortalAI/Agent/mission_schedule.py): occurrences, epochs and run limits. [mission_recovery.py](../ApplicationSources/Windows/PortalAI/Agent/mission_recovery.py): classified read-only recovery and budget consumption. |
| Mission context and progress | [mission_context.py](../ApplicationSources/Windows/PortalAI/Agent/mission_context.py), [mission_memory.py](../ApplicationSources/Windows/PortalAI/Agent/mission_memory.py), [mission_activity.py](../ApplicationSources/Windows/PortalAI/Agent/mission_activity.py): bounded model input, persistent memory, nonauthoritative activity. [mission_index.py](../ApplicationSources/Windows/PortalAI/Agent/mission_index.py): lightweight list indexes, not execution state. |
| Mission permissions and external effects | [mission_modes.py](../ApplicationSources/Windows/PortalAI/Agent/mission_modes.py): mode allowlists. [mission_accounts.py](../ApplicationSources/Windows/PortalAI/Agent/mission_accounts.py): dedicated account dispatch and durable effect receipts. [account_services.py](../ApplicationSources/Windows/PortalAI/Agent/account_services.py): service adapters. |
| NativeChat/tool loop | [native_chat.py](../ApplicationSources/Windows/PortalAI/ControlCenter/native_chat.py): conversation and tool orchestration. [tool_protocol.py](../ApplicationSources/Windows/PortalAI/ControlCenter/tool_protocol.py): structured tool responses and bounded repair. |
| Chat stall assistance | [coding_stall.py](../ApplicationSources/Windows/PortalAI/ControlCenter/coding_stall.py), [task_progress.py](../ApplicationSources/Windows/PortalAI/ControlCenter/task_progress.py): request-scoped intervention at completed call boundaries. Distinct from mission process supervision. |
| Rolling context and exact evidence | [chat_working_memory.py](../ApplicationSources/Windows/PortalAI/ControlCenter/chat_working_memory.py), [persistent_memory.py](../ApplicationSources/Windows/PortalAI/ControlCenter/persistent_memory.py): compact projections, retained raw exchanges and later retrieval. |
| Source inspection/editing | [maintenance_tools.py](../ApplicationSources/Windows/PortalAI/ControlCenter/maintenance_tools.py): maintenance tool routes. [Coding navigation notes](Coding_Navigation_r49.txt) describe search/maps/receipts. |
| Web research | [web_tools.py](../ApplicationSources/Windows/PortalAI/Agent/web_tools.py), [web_tool_api.py](../ApplicationSources/Windows/PortalAI/ControlCenter/web_tool_api.py), [web_research_evidence.py](../ApplicationSources/Windows/PortalAI/ControlCenter/web_research_evidence.py): providers, tool interface and evidence preservation. |
| Resource admission and GPU handoff | [runtime_policy.py](../ApplicationSources/Windows/PortalAI/Agent/runtime_policy.py): policy, memory/storage admission, portable environment and atomic JSON. [service_manager.py](../ApplicationSources/Windows/PortalAI/Agent/service_manager.py): owned services and exclusive GPU lease. [chat_priority.py](../ApplicationSources/Windows/PortalAI/Agent/chat_priority.py): direct-chat priority over missions. |
| Accounts, vaults and storage recovery | [local_accounts.py](../ApplicationSources/Windows/PortalAI/Agent/local_accounts.py), [profile_paths.py](../ApplicationSources/Windows/PortalAI/Agent/profile_paths.py), [profile_workspace.py](../ApplicationSources/Windows/PortalAI/Agent/profile_workspace.py), [profile_runtime.py](../ApplicationSources/Windows/PortalAI/Agent/profile_runtime.py): authentication, captured session identity, encrypted generations and lifecycle. |
| Lazy restoration and verified shutdown | [profile_hydration.py](../ApplicationSources/Windows/PortalAI/Agent/profile_hydration.py), [profile_lazy_state.py](../ApplicationSources/Windows/PortalAI/Agent/profile_lazy_state.py), [profile_shutdown.py](../ApplicationSources/Windows/PortalAI/Agent/profile_shutdown.py): authorized file restoration, pending state and owned-writer shutdown before sealing. |
| Media and scientific bridges | [ai_tools.py](../ApplicationSources/Windows/PortalAI/Agent/ai_tools.py), [science_tools.py](../ApplicationSources/Windows/PortalAI/Agent/science_tools.py), [tool_contracts.py](../ApplicationSources/Windows/PortalAI/Agent/tool_contracts.py): command routing/contracts. Individual bridge/worker modules are indexed by filename and symbols; upstream runtimes/models are not original PortalAI implementations. |
| UI and offline Help | [ControlCenter](../ApplicationSources/Windows/PortalAI/ControlCenter), [application Documentation](../ApplicationSources/Windows/PortalAI/Documentation): native widgets, settings, mission/schedule views and offline explanations. |
| OS launch and process ownership | [Launchers](../ApplicationSources/Windows/PortalAI/Launchers), [linux_job.py](../ApplicationSources/Linux/PortalAI/Agent/linux_job.py), [macos_job.py](../ApplicationSources/Mac/PortalAI/Agent/macos_job.py): platform startup and process-lifetime mechanisms. These are not a general-purpose OS sandbox. |
| Installer/update/recovery | [InstallerSources](../InstallerSources), [portable_update.py](../ApplicationSources/Windows/PortalAI/Installer/Windows/portable_update.py): exact public-file plans, compatibility/edition checks, closed-account guard, backups, verification and rollback. |
| Projection and Home Assistant | [Projection guide](PROJECTION.md), [companion source](../Utilities/Projection/source), [application HomeAssistant](../ApplicationSources/Windows/PortalAI/HomeAssistant): separate companion/receiver and host protocol adapters. Historical prototype files are not the active deployment. |
| Regression and process tests | [Maintenance/Tests](../ApplicationSources/Windows/PortalAI/Maintenance/Tests), [Tools](../ApplicationSources/Windows/PortalAI/Tools): disposable fixtures and explicit smoke tools. Read a smoke tool's scope before using it; some require authentication or real hardware. |

## What the inventory establishes

`tools/source_inventory.py` statically indexes non-vendored application code,
including tests and scripts, without importing the application. It records each
path, SHA-256, platform, line count, Python module overview and top-level symbols.
It explicitly lists modules without an overview. That is a documentation
maintenance queue, not proof that they lack all comments, tests or Help coverage.

This map is architectural navigation, not an assertion that every function has a
complete specification. The audit distinguishes missing publication, weak
navigation, historical documentation and untested guarantees. Raw GitHub URLs for
public Academic files work without extracting binaries; Full source remains
subject to its existing repository access policy.
