Windows r53 fixes listener ownership detection that could prevent Nice from starting for typed or hands-free messages. Windows netstat omitted a real listening socket on the affected host; the native Windows listener-only TCP table returned its correct process. PortalAI now uses that API for IPv4/IPv6 and rechecks a socket that appears between PID snapshots. Executable ownership, model readiness and Stop protections remain enforced. Unknown or foreign listeners are never adopted or killed by port alone.

Mic dictation remains local CPU transcription. Hands-free still displays Nice's text and speaks the final reply using the r52 voice controls. Exit PortalAI normally and reopen after updating.

Validation: 158 focused checks on each SSD and each extracted Windows edition (157 pass, one existing skip). Actual IPv4/IPv6 listener ownership, established-only exclusion and refusal of an unrelated live listener passed. Installer checks: 45 per edition (44 pass, one existing skip), all payload/source hashes and embedded source verified. Seven POSIX-only cases were excluded from Windows execution; three already errored on the unmodified baseline.

Live-model acceptance remains incomplete: the isolated test executable disappeared and Windows denied restoring that test path. The installed D/E executables remained intact. No antivirus settings or exclusions were changed. A completed live model stop/restore, physical microphone conversation and full fresh recipient installation are not claimed.

Full and Academic retain their respective policies. Universal setup selects Windows r53 plus unchanged Linux/Mac r51. Runtime/model components are downloaded separately by the installer.

[Explanation and source map](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/LISTENER-OWNERSHIP-r53.md) · [Validation](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/RELEASE-VALIDATION-r53.json).
