# Windows r60 — capability intelligence

Adds independent output checks, bounded external project navigation and guarded undo, explicit memory correction, better document structure/retrieval, optional model calibration, and Ctrl+K search with quiet notifications.

[Feature usage, source modules, limits and storage caps](CAPABILITY-INTELLIGENCE-20261101.txt) · [Validation evidence](CAPABILITY-INTELLIGENCE-VALIDATION-r60.json) · [Release notes](RELEASE-r60.md).

Runtime testing fixed a misplaced automatic-rebuild guard, compatibility with minimal DOCX documents, and a Windows child-log cleanup race. Live model testing led to explicit, kind-specific verification schemas so models cannot omit the expected JSON value. Existing batch/raw-value verification callers remain supported.

No new models, runtimes or permanent services. D and E remain independent Full installations with an 80 GiB free-space floor. Work and recovery files stay on the SSDs. The deprecated C installation is excluded. Normal Exit and reopen loads this release. Linux/Mac remain r51.

The 1.7B end-to-end write-and-verify check passed. Both 1.7B and 4B completed the optional eight-question calibration at 6/8. Some separate 4B multi-tool attempts produced invalid batches and were safely blocked; measured calibration does not guarantee agent-task success. Computer Use was stopped with Escape, so desktop visual inspection is incomplete; automated hidden Tk checks passed. Other physical hardware tiers and a full fresh recipient install were not tested.

A bounded metadata-publication retry also handles transient Windows read/replace
sharing conflicts. It rechecks account/Stop fences before each attempt and never
repeats the action represented by the record.
