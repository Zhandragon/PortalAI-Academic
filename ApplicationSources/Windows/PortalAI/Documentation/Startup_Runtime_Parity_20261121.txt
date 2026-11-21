PortalAI Windows r81 - startup model display and Runtime history
Version: 2026.11.21-Desktop-r81

The Chat effort slider follows the saved explicit model, including a saved 27B
choice, even when an older effort snapshot still says Balanced. A successful
Automatic startup updates the display to the actual catalogued text model and
labels it Auto, without rewriting the saved model or linked voice choice.
Observations are scoped to the account and model policy. Later manual choices,
active requests, stale capability results, Stop and Exit keep their existing guards.

Runtime telemetry has its own tracked worker, independent of package inventory
and service probes. CPU/RAM/WDDM sampling targets 0.5 seconds for the first ten
seconds, one second until thirty seconds, then five seconds. Adapter queries
target two seconds during warmup and fifteen seconds afterward. Slow probes may
extend these intervals; they never overlap or trigger a busy catch-up loop.
The graph expands across actual observed history and grows to a five-minute
rolling window. Cached GPU values do not count as fresh observations. Missing
counters stay unavailable. Monitoring stops and closes its counter handles on Exit.

PLATFORM PARITY AUDIT
Windows includes r79 voice, computer-use, Stop and resizing plus r80 media planning
and shutdown fixes. Linux and macOS installer payloads and source stamps remain
experimental 2026.11.09-Desktop-r75. The app tour is present there, so the version
stamp alone does not describe every shared feature.
Both lack the new browser-use worker/runtime, streaming voice components,
ToolProcess ownership layer, reference/staged media planner and PortalAI navigation
module. Their chat, Stop, GUI and resizing implementations differ from Windows.
This audit does not certify all existing Unix behavior or native dependency support.
macOS also still uses a Linux /proc CPU-counter path; CPU telemetry needs a native
implementation before it can be claimed to work there. Native Linux/macOS testing
was unavailable on this Windows host. Their installer archives are unchanged.
See platform-parity-r80.json for the reviewed per-file baseline comparison;
"different" means contextual review is needed, not automatically a missing feature.

VALIDATION
Focused model-policy, startup, effort UI, telemetry, layout and navigation checks
are recorded in the release validation report. A disposable real Windows GUI
checked the saved choice, Automatic 27B receipt, later manual choice, stale Stop
receipt, actual host telemetry, normal Exit and verified account sealing.
The initial live run collected 42 CPU/GPU samples across 35 seconds, with 21
samples in the first ten seconds and a final five-second interval. No production
account or model service was opened by that fixture. The startup receipt is
synthetic; this is not a new 27B inference or clean-recipient installation claim.

DEPLOYMENT
Full, Academic and 72-hour Trial retain their edition rules and dependency pins.
Use normal Exit, verify sealing, review exact public-file hashes and apply through
Tools/portable_update.py or the supported installer update flow. Keep accounts,
keys, model choices, connection settings, models and outputs. Aoostar requires
its own receiving-machine review and acceptance; the handoff is not deployment.
