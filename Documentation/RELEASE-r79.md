# Windows r79: computer use, reliable Stop and responsive panels

Nice can now use text accessibility controls through a scoped adaptation of
[iFurySt Open Computer Use](https://github.com/iFurySt/open-computer-use/tree/v1.1.5)
and interact with websites through local
[browser-use](https://github.com/browser-use/browser-use/tree/1.0.7).
Text-only Qwen models can use these tools; pixel actions still require vision.
Desktop access requires an explicit window grant for the current login.
Browser actions use bundled headless Chromium and a separate disposable profile.

Stop cancels pending starts and owned command trees, including detached children
whose launching shell has already exited. It also closes Workspace workers and
pauses mission hooks and schedules started outside the current chat. Completed
external effects cannot be undone by Stop; uncertain results are not replayed.

Runtime cards and Controls recalculate from their own available width. Tracker
graphs redraw at their actual canvas dimensions; narrow panels wrap their text
and controls. The validated voice decoding acceleration, streaming buffers and
portable CPU preparation from the local r78 build are included.

Dependencies remain on the portable drive. No host Python, Node, browser service
or browser-use cloud account is required. Windows uses built-in PowerShell and
UI Automation. Full, Academic and 72-hour Trial policies remain edition-specific.
Experimental Linux/macOS packages remain r75; this is a Windows x64 update.

Validation: 305 headless regression checks across the installed source and both
edition trees, including real detached-child, controller-exit, mission and
cross-hook cancellation tests. A real headless browser passed navigation,
accessible state, fill, click, stale-token/private-URL/guest-input rejection and
owned-tree shutdown. The desktop accessibility fixture returned scoped controls;
further input tests were deferred after a foreground-window change. Full visual
resizing, actual Qwen 4B inference, fresh-recipient installation and native
non-Windows execution are not claimed. Prior RTX3090 voice generation and
relocated playback checks are documented in the voice guide.

Installers verify every payload member, preserve existing account/model data
through the normal updater, and require normal Exit/reopen for activation.
Online Windows/Universal kits reconstruct the same Windows payload from the
public Academic release plus the appropriate edition overlay.

[Detailed guide](../ApplicationSources/Windows/PortalAI/Documentation/Computer_Use_Stop_Resize_20261121.txt)
· [Voice guide](../ApplicationSources/Windows/PortalAI/Documentation/Voice_Streaming_20261121.txt)
