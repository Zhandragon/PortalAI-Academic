PortalAI Windows r85 - bounded tool recovery and reusable workflows
Version: 2026.11.22-Desktop-r85

Nice could stop when Qwen reached its reply-token limit while serializing a tool
call, even after only reading information. The observed video request stopped
before any generation call reached the backend. This update keeps the incomplete
batch withheld and allows one fresh, concise structured correction after read-only
history, with extra thinking disabled for that correction only. It shares the
existing one-repair budget; partial JSON is never executed or continued. Login,
Stop, context limits, duplicate-action checks and prior-effect guards remain.

Audited public retrieval routes (read, site/catalog search, resource discovery,
parsed data and media metadata) now share the existing read-only fetch classification.
A failed metadata lookup no longer incorrectly blocks a later fresh correction.
Arbitrary HTTP requests, downloads and browser actions remain excluded.
Empty page-find results explain literal matching and how
to inspect the cached document instead of repeating unsuccessful search strings.
Supplied images are inspected before deciding whether external references are
needed. Merely using a video tool does not require a research detour.

Includes r83 semantic media assessment: requested fidelity, components,
relationships and uncertainties determine reference needs and staging separately.
Missing assessment remains unknown. Topic classifiers and fixed-scene recipes
have been removed. General computer/browser workflows, local commands and files,
coding model/tool routing, science tools and multi-step media sequencing are
retained. See WORKFLOW-GENERALITY-r85.txt for the scope and limits of the audit.

Validation: 220 regression cases per edition; Full 219 passed with one previously
documented baseline mismatch, Academic 218 passed with two. No new failures or
errors. This includes all 23 media-planning cases and 11 truncation-recovery cases.
Synthetic SSE/model fixtures validate control flow, not live generation quality.
No clean recipient installation, live-model/video benchmark or native Unix
acceptance was performed. Detailed results are in VALIDATION-r85.json.

The local Windows installation was updated with the supported staged updater
after idle/normal Exit and account sealing, and reopened to the normal sign-in
panel. The release stamp and distribution receipt both report r85. Fifteen staged
files were verified; four sampled preference files and the
existing simulation hash were unchanged. No private chat is included in source,
release packages or handoff evidence.

Windows Full, Academic and Trial retain edition policies and dependency pins.
Includes r79-r84. Experimental Linux/macOS packages remain r75. The cumulative
Aoostar bundle includes the unapplied earlier handoff, r85 source deltas, hashes
and receiving-machine checks; it is a handoff, not a remote deployment.
