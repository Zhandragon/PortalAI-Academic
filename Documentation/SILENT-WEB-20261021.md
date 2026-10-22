# Silent web tools — 2026-10-21

The background web worker now starts without a Windows console. Redirecting its
pipes alone allowed Windows to create a visible command window when PortalAI
started the worker from the GUI. The fix adds `CREATE_NO_WINDOW` to that one
launch while preserving its job ownership, start gate, JSON pipes and Stop
cleanup. Legacy search/image-search command routes already hide their processes.
Playwright continues to hide its driver and run Chromium headlessly.
The Windows/Linux payloads also restore the shared `worker_process_options`
helper that the web client imports. The installed D: copy and Mac payload
already had it; the omission was found by the exact packaged-worker regression.

Use normal Exit and allow account sealing to finish, then restart PortalAI to
load updated installed code. Clean installers are for a new folder and refuse
existing account roots. No account reset, pairing change or new model download
is needed for the source-only hotfix. Linux/Mac process-group behavior is unchanged.

## Downloads

Release: [v2026.10.21-r3](https://github.com/Zhandragon/PortalAI-Academic/releases/tag/v2026.10.21-r3).

| Platform | Installer | SHA-256 |
| --- | --- | --- |
| Windows | [PortalAI-Academic-Windows-Installer-20261021-r5.zip](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.21-r3/PortalAI-Academic-Windows-Installer-20261021-r5.zip) | `b7bdde297a30013033c2f5f3bb371bd462194216a2bfa48646e12bee6b640ff3` |
| Linux | [PortalAI-Academic-Linux-Installer-20261021-r4.tar.gz](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.21-r3/PortalAI-Academic-Linux-Installer-20261021-r4.tar.gz) | `dabb2f631c27a4e9e6a707295cb42074e6b57d98efdf347222f70625ccda7b22` |
| Mac | [PortalAI-Academic-Mac-Installer-20261021-r5.tar.gz](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.21-r3/PortalAI-Academic-Mac-Installer-20261021-r5.tar.gz) | `fb5d9b61f753b2cd9e45e35a28f5b2e91b023b4483bd0e1faa814dd9f78ccc4b` |

Both editions retain the previous web tools, agent communication, configurable
ports and Mac Projection/HA packages. The standalone projection bundles remain
at their earlier immutable release URLs. Full keeps its normal model choices;
Academic retains standard-only policy and separately rebuilt, hash-pinned setup
launchers. Older downloaded Academic launchers retain their original packages.

## Validation

- 85 local Windows regressions passed, including real worker/Chromium processes,
  search/image-search, account checks, web bounds and worker cleanup.
- The new regression checks `GetConsoleWindow()==0`, UTF-8 pipe round trips,
  process reuse, absence of visible owned browser windows, and all captured
  process handles signalled after Stop. No production account was used.
- Exact packaged Full and Academic Windows tests cover web/agents, certificate
  packaging and the hidden worker (25 tests per edition). Academic policy tests
  run for each platform's source (23 per platform, executed on Windows).
- All six outer archives, Windows payload member hashes and destination maps,
  native payload pins, required/all-component Windows plans and native shell
  syntax were checked. Exact Academic launchers passed prepare-only extraction
  and every pinned extracted-file hash. Native launchers were exercised through
  Git Bash on Windows; this is not a native Mac/Linux installation test.
- The Aoostar delta updater was tested for read-only behavior, conflicts, active
  session refusal, verified backup/application and repeat no-op application.

See [detailed checks](SILENT-WEB-VALIDATION.json). Physical Aoostar deployment,
native Mac/Linux execution and live HA acceptance remain recipient checks.
The previous feature release's validation limits remain in
[the earlier release notes](UPDATE-20261021.md).

Bounded live public web smoke: five of six checks passed. The initial DuckDuckGo query received HTTP 403 bot challenges from both HTML and Lite providers. The separate Lite fallback query, cache reuse, public page fetches and image search/download passed. No challenge was bypassed. These external access results are separate from the passing console and lifecycle regressions.
