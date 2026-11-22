PortalAI Windows r84 - bounded tool recovery and reusable workflows
Version: 2026.11.22-Desktop-r84

Nice could stop when Qwen reached its reply-token limit while serializing a tool
call, even after only reading information. The observed video request stopped
before any generation call reached the backend. This update keeps the incomplete
batch withheld and allows one fresh, concise structured correction after read-only
history, with extra thinking disabled for that correction only. It shares the
existing one-repair budget; partial JSON is never executed or continued. Login,
Stop, context limits, duplicate-action checks and prior-effect guards remain.

Structured web reads now receive the same read-only classification as the existing
registered fetch route. Empty page-find results explain literal matching and how
to inspect the cached document instead of repeating unsuccessful search strings.
Supplied images are inspected before deciding whether external references are
needed. Merely using a video tool does not require a research detour.

Includes r83 semantic media assessment: requested fidelity, components,
relationships and uncertainties determine reference needs and staging separately.
Missing assessment remains unknown. Topic classifiers and fixed-scene recipes
have been removed. General computer/browser workflows, local commands and files,
coding model/tool routing, science tools and multi-step media sequencing are
retained. See WORKFLOW-GENERALITY-r84.txt for the scope and limits of the audit.

Validation: 219 regression cases per edition; Full 218 passed with one previously
documented baseline mismatch, Academic 217 passed with two. No new failures or
errors. This includes all 23 media-planning cases and 10 truncation-recovery cases.
Synthetic SSE/model fixtures validate control flow, not live generation quality.
No clean recipient installation, live-model/video benchmark or native Unix
acceptance was performed. Detailed results are in VALIDATION-r84.json.

The local Windows installation was updated with the supported staged updater
after idle/normal Exit and account sealing, and reopened successfully showing
r84. Fifteen staged files were verified; four sampled preference files and the
existing simulation hash were unchanged. No private chat is included in source,
release packages or handoff evidence.

Windows Full, Academic and Trial retain edition policies and dependency pins.
Includes r79-r83. Experimental Linux/macOS packages remain r75. The cumulative
Aoostar bundle includes the unapplied earlier handoff, r84 source deltas, hashes
and receiving-machine checks; it is a handoff, not a remote deployment.
