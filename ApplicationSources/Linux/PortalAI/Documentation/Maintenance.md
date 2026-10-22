# PortalAI maintenance — 2026-10-16

Start with System Test. If it identifies a problem, select that component under Targeted Diagnostics. The selector is alphabetical, with All last. Full diagnosis covers the catalog; Fresh-machine readiness evaluates portability/admission; Verify media stack checks public routes and assets. These buttons never repair or install packages automatically.

The main Maintenance tab separates Checks and reports, Cleanup plans, and Delete data. Context menus use the same current labels and callbacks. Safe Cleanup Plan and Root-only Cleanup open their previews; data deletion still requires its explicit confirmation. The GUI serializes maintenance checks. Avoid full model hashes or duplicate scans during active generation, and stop heavy I/O if Windows reports device disappearance or delayed writes.

Dependency Isolation Test Standard checks GUI, account crypto libraries, foundation and both science layers. Full adds speech/voice/media/music understanding and a separate ROCm process. It does not mix NVIDIA and AMD packages, run inference, download models, pair HA, or prove an OS sandbox. Optional missing dependencies and failed imports remain visible.

Maintenance Reports opens the active account’s Data/Maintenance folder. Current and Previous outcomes, timestamps, failure/timeout status and full-text Copy are preserved. A saved result is historical, not a new pass.

Storage Audit reports logical sizes, free space, output reserve, minimum free-space floor and asset budget. It skips junctions/symlinks and reports unreadable files. The default policy reserves 100 GiB for outputs plus max(50 GiB, 10% of volume capacity). Maintenance now exposes these disk reserves with sliders and numeric entry; Storage Audit reports the saved values. Managed checks are not OS quotas on Full-mode shell commands.

Deep Duplicate Scan is read-only. Files at least 1 MiB are grouped by size, filtered by samples, then compared with full SHA-256. Changed files are excluded and reported. Hard-link identities are distinguished from separate duplicate files. Logical duplicate bytes are not guaranteed physical reclaimable bytes. Models, runtimes and user data are never auto-deleted.

Safe Cleanup Plan allows only compiled Python bytecode beneath first-party cache directories. Apply rechecks scope and file identity/size/mtime. It preserves models, package runtimes, science results, missions, outputs, user data and backups. No whole model/cache tree is declared safe by the dependency-import check.

The Windows KiCad payload under Tools/KiCad and its staging tree are vendor packages, excluded from first-party cache cleanup and source scans. The verified installer remains under Runtime/Downloads; its provenance and per-file hashes are recorded in Maintenance/Imports/windows-kicad.json.

Root-only Cleanup previews a reversible archive. Apply requires matching checksums in Backups/PortalGUI_before_20261009 and records original paths and SHA-256 in Maintenance/Archive/Root-*/_archive-journal.json. Historical installers/shortcuts are inert recovery material and must not be run from the archive. User images and current master instructions remain where existing references expect them. The archive saves clutter, not SSD capacity.

Explicit Delete Web Cache / Outputs / Conversations controls are separate user-data operations. Do not use them to clean model dependencies. Code snapshots in Backups and C:/Users/genes/PortalAI-Recovery exclude weights and third-party runtimes; they are not complete SSD backups. Reports retain Current + Previous.

The Maintenance main tab, between Persistence and Help, contains Targeted Diagnostics and Maintenance & Storage. Packages is the component inventory, and Models is the current runtime/service view. Context and tray menus link to the same pages. New source-only diagnostic categories and their limits are described in Diagnostics.md.