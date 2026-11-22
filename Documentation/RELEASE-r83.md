PortalAI Windows r83 - semantic media assessment
Version: 2026.11.22-Desktop-r83

Nice previously returned no-reference/no-staging flags when a request did not
match a small keyword list. Its general guidance also prescribed two specific
example scenes. This update removes the classifier and those prescriptions.

Before visual generation, Nice now records its understanding of the requested
fidelity, visible components, relationships and critical uncertainties, with
reasons. Reference needs and composition complexity are separate judgments.
An omitted assessment is unknown, never a false assertion that research is
unnecessary. Simple understood scenes need only this short assessment.

Uncertain structure requires actual reference images and comparison of read
source pages. Complex compositions require a staged plan. Existing reference
inspection, output review and previous-image edit continuity guards remain.
The same preflight applies to registered image/video tools and shell routes;
help, audio and unrelated tools remain available. A plan cannot be downgraded
by submitting a simpler subprompt or replacing its recorded assessment.

The model supplies the semantic judgment. Runtime checks validate and enforce
the workflow; they do not independently certify understanding or image accuracy.
Unavailable reference, vision or editing capabilities must be reported.

Validation: all 23 media-planning regression cases passed in both editions.
The broader 161-test suite has 160 passes in Full and 159 in Academic, with
one/two previously documented baseline mismatches respectively. Suites overlap.
These are deterministic tests with supplied model judgments, not a live-model
generalization benchmark. Package details and limitations are recorded in
VALIDATION-r83.json. A clean recipient installation and native Unix acceptance
remain untested by this release.

Windows Full, Academic and Trial retain their edition rules and dependency pins.
This cumulative update includes r79-r82, including generated-file destinations,
known rejected-write outcomes, voice, computer/browser use and shutdown fixes.
Experimental Linux/macOS packages remain r75. The user's windmill simulation
is not modified or bundled. Use normal Exit, verified account sealing and the
supported updater; preserve accounts, models, outputs, keys and settings.

The bundled Aoostar handoff includes the unapplied r79-r82 handoff plus r83
source deltas and receiving-machine checks. It is not a remote deployment.
