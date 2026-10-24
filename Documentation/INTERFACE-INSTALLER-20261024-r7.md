# PortalAI interface and installer update — 2026-10-24 r7

Right-click a mission or schedule to see its available actions. Mission actions include Run, Stop, Resume, Review: retry, Review: skip, Delete and Restore. Schedule actions operate on its current run and preserve its saved timing and run limits. Review does not implicitly enable a paused schedule. Actions unavailable for the current state are disabled. Keyboard users can use Shift+F10 or the Menu key; Mac users can Control-click.

Deleting a stopped mission or removing a schedule now asks for confirmation inside the PortalAI window, using its current theme. Records remain recoverable through the existing Deleted/Removed views. Confirmations recheck account access before making a change. A menu opened before an active run changes cannot approve that old review action.

Projection's connection manager now uses the main desktop's graphite dark and ivory light palettes, rounded controls and decorated borders. Windows has custom title controls and resize edges, retaining taskbar/tray minimize and restore. Existing custom appearance choices and connection data are preserved. Restart the companion normally to load the update.

Windows installers show current-component byte progress and a separate overall bar for selected downloads, installation and checksum verification. The overall bar reaches 100% only after successful publication. Recovery and other steps without a byte total show activity while the overall bar holds its measured position. Progress updates replace the current display instead of repeatedly adding a model name to the log. Both installers and the Academic download launcher support matching light/dark themes.

Mac/Linux command-line installers show completed-stage progress. Model transfers show a byte progress bar, including retained/resumed bytes. Color is used only in an interactive terminal and respects NO_COLOR. Stages are milestones rather than estimates of elapsed time. Certificate checks, pinned hashes, required components, filesystem checks and free-space admission remain enabled.

Validation: 123 installed-application checks passed, with one expected skip; 39 Projection checks and six target-lifecycle checks passed; 28 installer checks passed per edition. Actual synthetic installations exercised extraction, readback, recovery registration and publication in both engines. Native Windows forms were compiled and rendered in both themes; model byte ratios, bounded logging, required selections and the below-100% completion guard were checked. Release archives and embedded sources are verified separately before publication.

Physical Linux/macOS GUI acceptance and a fresh installation of every optional model/runtime were not performed. These changes do not establish that an arbitrary model can complete every scheduled objective.

The r6 release remains available unchanged. Use the complete r7 package in a new setup folder for these additions. Do not replace a manifest inside a running or partially completed older installation.
