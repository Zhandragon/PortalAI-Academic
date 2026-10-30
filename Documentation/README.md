# PortalAI (Academic) documentation

[Welcome page and gallery](../README.md) · [Download and install](../README.md#download-and-install)

Documentation and help are already inside PortalAI. Open **Help** to browse or search offline topics, and right-click controls for context-aware guidance. These repository guides focus on distribution, installation and connecting optional companions.

Current packaged release: [r51](RELEASE-r51.txt). Later source patch: [mission recovery and source audit](SOURCE-AUDIT-20261029.md). Upgrade background: [unified r45](UNIFIED-20261025-r45.md).

| Topic | Guide |
| --- | --- |
| Install and launch | [Installation and platform requirements](INSTALLATION.md) |
| Drive format: Windows NTFS, Mac APFS, Linux ext4 | [Drive preparation and filesystem recommendations](INSTALLATION.md#drive-format-and-preparation) |
| Home Assistant link, pairing and projection | [Projection guide](PROJECTION.md) |
| Interface and hardware controls | [Gallery and settings overview](../README.md#a-look-inside) |
| Local accounts and encryption | [Privacy and local accounts](../README.md#privacy-and-local-accounts) |
| Antivirus detections | [llama.cpp and antivirus help](../README.md#antivirus-and-the-llamacpp-server) |
| Companion downloads | [Utilities](../README.md#companion-utilities) |
| Build provenance and verification | [Academic build notes](README.txt), [current validation](VALIDATION.json), [publishing guide](PUBLISHING.md) |
| Screenshot provenance | [Artwork notes](assets/README.md) |

Academic enforces standard/censored routing and excludes abliterated/uncensored assets. Its visible variant controls do not unlock those assets.

Only Windows has been thoroughly tested; Linux has partial validation. macOS installation and other configurations may encounter errors. **macOS Projection is now packaged for Intel and Apple silicon (macOS 14+); native Mac acceptance remains pending.** Use the matching repository's issue tracker linked on the welcome page, and omit secrets and private user files from reports.

[Current web/agents/ports/Mac update](UPDATE-20261021.md) · [Usage](WebAgents/USAGE.txt) · [Mac setup](MacProjection/SETUP.txt).

[Silent web tools update and current installers](SILENT-WEB-20261021.md).

[Chat timeline update and current installers](CHAT-TIMELINE-20261022.md).

**Earlier update: mission review instructions.** Add corrections or responses to a paused mission or scheduled run, retain review history, and re-enable reviewed schedules. [Details and current installers](MISSION-REVIEW-20261022.md).


Current distribution correction: [one-off migration removal](DISTRIBUTION-SCOPE-20261024-r9.md) and [validation](DISTRIBUTION-SCOPE-VALIDATION-20261024-r9.json).

Current update: [shutdown and Projection repair](SHUTDOWN-20261024-r10.md) and [receiving validation](SHUTDOWN-VALIDATION-20261024-r10.json).

## Implementation and source

- [Architecture and source map](SOURCE-MAP.md)
- [Mission recovery: exact behavior, limits and tests](MISSION-RECOVERY.md)
- [Application module index](MODULE-INDEX.md) and [machine-readable source inventory](SOURCE-INVENTORY.json)
- [2026-10-29 audit: publication gaps, installed variants and validation](SOURCE-AUDIT-20261029.md)

**Follow-up bug fixes (2026-10-29):** schedule backoff, worker launch recovery, and durable failure records. [Findings, source, tests and SSD patch](BUG-REVIEW-20261029.md).

**Workspace update (2026-10-29):** [knowledge, MCP, workflows and Windows computer use](WORKSPACE.md), [validation](WORKSPACE-VALIDATION-20261029.md), and [code/runtime bloat audit](BLOAT-AUDIT-20261029.md).
