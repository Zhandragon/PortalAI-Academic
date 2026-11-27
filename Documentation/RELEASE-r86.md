PortalAI Windows r86 - reliable image lookup and editing

Nice could lose tools while loading another tool group, over-collect references,
and repeatedly serialize malformed web calls before reaching image generation.
This release keeps loaded tools available, bases reference needs on actual gaps,
preserves direct image URLs in compact context, and validates bounded tool calls.
A second public image provider and explicit failed-page evidence reduce repeated
lookups when another provider or source is unavailable.
Planning and argument checks now run before an action is recorded as attempted,
so correcting a rejected request does not trigger a false duplicate-action block.
Image queries start with the requested subject words, and final review feedback
identifies exact unchecked constraints so the same output can be reviewed again.
Locally invalid web arguments receive one action-specific schema correction that
requires the missing fields; repeated invalid calls stop with the saved evidence.
Simple assessed outputs can be reviewed without creating a plan after generation.
Image inspection uses the packaged Pillow runtime; no extra installation is
needed. The release builder also verifies first-party payload dependencies.
Streaming and saved response headers now say Nice immediately, avoiding the
brief Qwen label before the branding refresh. Technical model names remain.
The base 9B image workflow now uses ComfyUI's guided native sampling graph,
correcting the distorted output from the previous 8-step unguided graph.

The changes apply to image workflows generally. There are no subject-name rules,
special likeness routes, or prompt-specific fixes. Stop, captured accounts,
context budgets, effect receipts and protection against repeated actions remain.

Full and Academic each passed 369 focused tests; 1139 owned source/config files
passed syntax checks. Full-edition actual model tests cover two-image lookup/editing and an
unrelated image request. See VALIDATION-r86.json for measured outcomes, timing,
runtime settings and verification limits. External sources can still rate-limit
requests and generated image quality varies.

Windows Full, Academic and Trial retain their dependency pins and edition policy.
The accompanying online kits are Full online16 and Trial online13. Experimental
Mac/Linux native payloads remain r75; this Windows validation does not establish
physical Mac/Linux execution. Complete cross-platform setup bundles are released
separately as bundle7, retaining the existing optional model and companion setup.
