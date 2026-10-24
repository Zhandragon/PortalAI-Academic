# Selective startup, recovery and account connections

PortalAI October 24, 2026 r8: reviewed Aoostar integration

Account connections can be imported explicitly by a signed-in administrator,
with named service operations and encrypted credentials. A new import creates
an unarmed mission and a paused schedule. Repeating an import preserves and
accurately reports any subsequent activation. See Account_Connections_20261024.txt.

Mission/schedule lists use compact verified summaries; full histories load on
selection or execution. Startup remembers the last successfully selected chat.
Authenticated interrupted-login recovery preserves untouched encrypted bodies
instead of restoring them only to reseal them. See Lazy_Startup_Recovery_20261024.txt.

The receiving merge preserves r7 mission/schedule right-click actions, themed
internal confirmations, decorated Projection window and installer progress.
Model-selection tests and selected-chat-history tests remain separate suites.
Platform-specific process launching and Academic standard-model policy remain.

Receiving validation: 543 checks, zero failures/errors, one expected skip; six
owned process checks passed. Windows native UI checks used disposable fixtures.
They cover connection encryption/startup pipes, authentication, lazy histories,
interrupted recovery, schedule/review/Stop and the retained context-menu controls.
No owner account, credential import, mission execution or external write was run.
Physical macOS/Linux/Aoostar and complete fresh dependency installation remain
unvalidated; source/package integrity checks do not imply hardware acceptance.

Normal PortalAI restart loads this update. No new automatic startup or schedule
activation is introduced. Upstream runtime/model download pins are unchanged.

Archive-link installation failure: older r5 setup launchers remain tied to their
original version. Reopening one does not update it to the current release.
Use the current r8 installer for a new installation. To resume a retained r5
package and its existing downloads, use the matching r5 Resume-Fix executable
from the r6 release directly beside that package's release.json and payload.zip.
That repair completes the original r5 payload; it is not an application upgrade.
