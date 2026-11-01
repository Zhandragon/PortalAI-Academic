# Windows r61: verified idle shutdown repair

Fixes repeated verified-shutdown failure when an idle chat's background document monitor remains alive. This regression was introduced with the r59 document monitor: account sealing waited for the monitor while the monitor waited for the account to end.

Idle shutdown now cancels Workspace resources before joining writers. The monitor also recognizes chat closure. Failed cleanup remains registered for retry and prevents a false success. Existing process ownership, account authentication and encrypted-sealing checks remain enforced.

Validation: **755 application checks per installed SSD and per extracted Windows edition: 754 passed, one unavailable symlink fixture skipped**. Installer checks, seven embedded source/runtime resources, catalog routing and the Academic compiled download-launcher preparation were verified. The real disposable Academic GUI closed in **14.38 seconds**, joined its monitor, sealed its account, and preserved saved content across authenticated reopening. No production account was used for tests.

Added payload: **7,555 bytes** relative to r60. No new dependencies, models or services. D/E remain independent Full installations with more than 80 GiB free. Windows and Universal Windows routes are r61; Linux/Mac remain r51. Full fresh-recipient installation and other physical hardware were not tested.

Running controllers retain their loaded code until restart. This update does not force-close a session or bypass normal authenticated crash recovery.

[Repair and source](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/IDLE-SHUTDOWN-r61.md) · [Validation](https://github.com/Zhandragon/PortalAI-Academic/blob/main/Documentation/IDLE-SHUTDOWN-VALIDATION-r61.json).
