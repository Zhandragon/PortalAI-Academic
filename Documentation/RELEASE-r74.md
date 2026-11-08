# r74: follow-ups while Nice works

Send remains available during inference and queues a follow-up without modifying the active request. Pending messages keep their attachment selection. Edit/remove the next item, or use Send now to stop the current response and send next after its worker exits. Ordinary Stop and errors pause queued work. Failed persistence does not silently lose pending messages or an unrelated draft.

The queue holds up to 32 pending messages in memory for the current chat. Changing chats/accounts or closing clears unsent queued items. This is not persistence across sessions or mid-generation instruction injection. [Operating guide](../ApplicationSources/Windows/PortalAI/Documentation/Followup_Queue_r74.md).

The release also fixes Windows long-path protocol recursion under Python 3.13. Existing science/schema/output-card and reasoning-summary repairs remain included. No model weights or native dependency pins change. Academic continues to exclude abliterated options and the abliterated coding specialist.

Both Windows editions passed 378 chat tests, including real Tk composer/event-pump tests with isolated stores and controlled workers. All four Mac/Linux edition source variants passed the 12 focused follow-up tests on Windows; this does not constitute native Mac/Linux recipient execution. Package and installer validation is recorded separately before publication.

Bundled GitHub downloads and the owner's D/E installer mirrors share the r74 application source. PayHip-online5 prepares the matching Full release and remains separate from bundled drive copies. Payhip sells only Full. Historical releases remain available.

The [expanded GUI gallery](GUI-PREVIEWS.md) shows Accounts, preference subtabs, Packages, Persistence, context help and the Windows tray menu. [Science examples](science-examples/README.md) document the exact synthetic DNA sequence, circuit problem and output-file workflow.


Additional verification: 59 worker/stop/maintenance/account/shutdown/filesystem checks passed with one platform skip in each Windows edition. Twelve controlled-worker queue checks passed against each Mac/Linux source variant on this Windows host. Installer checks passed 39 tests. Packaged Unix source syntax, imports, pins and edition policy were audited; this does not claim native Mac/Linux execution.
