PortalAI Windows r87 — optional multi-reference image editing

Edit with one to three reference images using optional Qwen-Image-Edit-2511.
Settings offers Auto, Lightning (4 steps), Full (40 steps), and Existing editing,
plus Auto, Guided, or Direct image planning. The existing planning, reference,
review, and GPU handoff tools remain available. Auto uses hardware and available
memory to select an applicable workflow, with the existing editor as fallback.

The chat model releases GPU memory for editing and is restored afterward.
Qwen editing currently requires supported Windows x64 NVIDIA CUDA hardware.
Existing image workflows remain available on other hardware. Hardware admission
thresholds are conservative estimates; physical inference was verified on an
RTX 3090 24 GiB with 32 GiB system RAM, not every supported GPU configuration.

Qwen model weights are NOT bundled or selected by default. An optional installer
choice links to publisher model cards and requires terms review before download.
The four pinned downloads occupy 30.99 GB (28.86 GiB) of disk space. Model licenses
and notices are included; runtime inference never starts an automatic download.

One paired two-reference edit took 139.187 seconds with Lightning versus 242.453
seconds with the existing FLUX workflow (42.59% less tool time). Peak VRAM rose
886 MiB and process commit about 0.75 GiB. Both outputs passed visual review for
the requested material edit. These are single-case measurements, not universal
speed or quality guarantees. A separate three-reference edit completed and
restored the 27B chat model successfully. The 40-step option's graph is validated
by focused tests; a separate 40-step GPU benchmark was not run.

Full and Academic passed 371 workflow regressions each. See VALIDATION-r87.json
for package checks, measured results and scope. No further benchmark matrix was
needed for this release. Full online17 and Trial online14 carry the same update.
Cross-platform bundle8 carries Windows r87; native Mac/Linux remain experimental
r75. This release does not add Qwen editing support to native Mac/Linux.
