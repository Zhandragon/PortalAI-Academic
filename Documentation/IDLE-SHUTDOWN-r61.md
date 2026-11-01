# Idle shutdown repair — Windows r61

The document monitor introduced in Windows r59 was registered as a chat writer,
but idle NativeChat.shutdown did not cancel ToolRuntime's background resources.
Its profile remained open until writers joined, so the monitor's profile guard
could not stop it. Verified shutdown timed out repeatedly waiting for that writer.
The live stack confirmed PortalAI-document-monitor waiting in knowledge_monitor.run.

Idle shutdown now calls ToolRuntime.cancel(cleanup_media=False), closing Workspace
services and revoking their operation epoch without starting a media cleanup worker.
The monitor also checks the chat's closing flag. Failed resource cleanup stays
registered for a verified retry and is reported as an incomplete shutdown.
Active-generation cancellation and all writer/process/sealing checks remain required.
No forced exit, account-marker override, skipped verification, or automatic recovery
is installed. A pre-update process retains its loaded code until restarted.

Source: ControlCenter/native_chat.py (NativeChat.shutdown), knowledge_monitor.py
(KnowledgeMonitor.check), workspace_services.py (close_all).
Regression tests: Maintenance/Tests/test_idle_shutdown.py and the existing account,
profile, writer and real Tk shutdown suites. Full/Academic package validation and
disposable GUI account sealing results are in the release validation JSON.

This source-only update adds no dependencies, model weights or persistent services.
Both portable installations remain independent. The 80 GiB free-space floor remains.
Windows is r61; Linux/macOS packages remain at their existing r51 revision.

For the owner's currently running D session, only on-disk code is updated by explicit
request. Its process, account marker, profile data and keys are not changed. The owner
will close it and use normal authenticated crash recovery if needed; that live recovery
has not been tested or claimed complete. The disposable recovery probe is separate.
