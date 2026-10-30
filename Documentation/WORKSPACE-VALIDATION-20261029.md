# Workspace validation — 2026-10-29

This source/runtime patch adds local document knowledge, MCP connections, saved workflows and Windows computer control. Both active Full Windows installations, D: and E:, received their own guarded offline kit at `Utilities/Workspace-20261029`. The deprecated C: installation was not inspected or updated. C: source checkouts were used for development/publication only; each SSD's installation and update kit are independently usable with its bundled Python.

## Results

| Check | Evidence and result |
| --- | --- |
| Installed regression suite | **215 tests passed on D: and 215 on E:** Workspace protocol/persistence/profile/computer boundaries; tool protocol and correction; runtime admission; missions and recovery; small-model prompts; encrypted profile hydration/crash recovery; account permissions; model/saved-chat selection; chat handoff; attachments; guarded updates. |
| New focused boundaries | 29 Workspace tests passed, including stale images, emergency revocation, current-turn vision context, authentication/cancellation, MCP grants/receipts and encrypted seal/reopen. Included in the 215-test suite. |
| Bloat report scope | Additional regression verifies case-insensitive pruning of bundled KiCad and package/library trees. No vendor file is treated as original code in this fixture. |
| Actual local retrieval/OCR | Quantized MiniLM embeddings, semantic/keyword search, real PNG and scanned-PDF OCR, page citations, incremental sync and reopening passed against D: and E: runtimes. |
| Actual MCP process handling | stdio initialize/discover/call/close and cancellation of a hanging owned worker passed. HTTP JSON/SSE handling also passed in the protocol tests. |
| Native UI | All four Workspace tabs rendered without Tk callback errors in light/dark/narrow layouts. Corrected screenshots were inspected. |
| Native computer inputs | Six synthetic-window checks passed: permission refusal, capture, stale-token refusal, real mouse/Unicode keyboard input, maximize/restore and revocation. Foreground testing was explicitly authorized. These were deterministic controller actions, not model-selected actions. |
| Local vision model | CPU Qwen3-VL-2B correctly read Knowledge, Connections, Workflows and Computer from a synthetic screenshot. 29.72 seconds; 1,083 prompt tokens; 32 output tokens; normal stop. This verifies model perception separately from input execution. |
| Real process recovery | Six supervisor smoke checks passed: duplicate-dispatch prevention, durable scheduling, autonomous resumption, uncertain-effect no-replay, descendant termination on controller crash and Stop during planning. Synthetic workers only. |
| Publication/installation integrity | Final installed files and independent kits are checked against the update manifest; no remaining changes in the updater's plan, no linked payload files, and both source scanners pass. Recovery backups and guarded rollback were exercised on intermediate revisions before installing the final package. |

The main regression modules are recorded in each SSD's `Maintenance/Validation/Capabilities-20261029/installed-regression-command.json`. Logs and receipts remain adjacent. The direct-input and vision results originate from D:; reference copies on E: retain that provenance. E: has its own retrieval/OCR/MCP and installed-regression results. Windows tests do not establish native Linux/macOS execution or physical unplug/crash durability on every filesystem.

## Failures investigated rather than hidden

- Source-only broad tests initially lacked the bundled runtime paths required by real child processes; installed-runtime checks replaced that incomplete setup.
- A stale compact-prompt assertion was updated to the current optional-manual contract without changing the application prompt.
- An older format-recovery test fixture pointed at a real installed account root. It now retains temporary state and mocks interpreter lookup only for mocked commands; account protections were not relaxed.
- One E: worker-resumption deadline failed while the suite overlapped other heavy checks. The recovery module then passed in isolation, and the full E: suite passed in 22.854 seconds without concurrent heavy tests. The earlier failure log is retained; its precise timing cause was not independently established.
- The initial smoke tool used hard-linked library copies. Those test-created links were removed and the tool now uses independent copies in an owned child process; the parent removes them after Windows releases loaded DLLs. Cleanup also handles copied read-only directory attributes. Reports and synthetic data remain; test runtime copies are removed.
- The bloat auditor initially included KiCad's bundled Python tree on a full installation. Traversal now prunes known vendor/runtime folders before parsing, with a dedicated scope regression.
- Avast quarantined D:'s CPU llama-server during the first vision attempt. At the user's request it was restored through the existing checksum-verified executable backup. The successful retry and final hash checks are recorded. No antivirus setting was changed by this work.

## NumPy and remaining limits

Science and Piper contain 923 byte-identical, separately stored NumPy/library files, about **39.8 MiB per SSD**, while sharing Bootstrap Python 3.12. A controlled probe imported Piper/ONNX Runtime with Science's NumPy and successfully performed a SciPy linear solve. That proves import/basic numerical compatibility for this pair; it does not validate a complete loader/installer/repair migration. Existing copies remain in place. New Workspace features reuse installed libraries and add no NumPy copy. Any future common layer should remain on each SSD, without references to C: or the other SSD. Other Python versions, operating systems and GPU environments require separate compatibility checks.

No existing model, runtime, owner output or historical recovery directory was deleted as bloat. The new runtime is approximately 161.4 MiB. Unused generated launchers with build-drive paths are omitted. Shared source is individually browsable in Full and Academic Windows/Linux/macOS trees; original r51 installer archives were not rebuilt. MCP supports tools over stdio and Streamable HTTP, not every MCP extension. Computer control is Windows-only; arbitrary autonomous desktop task success, accessibility trees, drag gestures and multi-monitor/high-DPI acceptance remain unproven or unimplemented as described in the [Workspace guide](WORKSPACE.md).
