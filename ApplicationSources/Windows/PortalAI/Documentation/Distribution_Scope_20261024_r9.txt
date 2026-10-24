PortalAI distribution scope correction - October 24, 2026 r9

The one-off connection-and-mission import was created for the originating
Aoostar installation. It is not a public setup workflow. The public Accounts
menu, GUI startup options and bootstrap no longer expose it, and its importer,
source-credential readers, setup dialog and migration-specific tests/guides
are excluded from clean installer payloads.

General encrypted account connections and service adapters remain, along with
selective history loading, authenticated recovery and remembered chat selection.
Existing user missions, schedules, connection bundles and account data are not
deleted or altered. Normal first-account creation and history import/export
remain separate supported workflows. No mission is created or activated by this
correction. Normal PortalAI restart loads the installed source update.

The r8 handoff and clean packages did not contain the sender's mission database,
setup request, credentials or private account records. The scope error was the
distribution of its one-off migration workflow as a reusable product feature.
The receiving audit and validation are recorded with the r9 release.
