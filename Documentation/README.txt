CURRENT: v2026.10.21-r2. Web tools, agents, ports and Mac Projection.
See UPDATE-20261021.md and PUBLISH-VALIDATION.json. Academic restrictions remain.

Historical baseline notes:
CURRENT: Academic 2026-10-21 r1. Access-request notice added to the welcome panel.
See the root README and Documentation/VALIDATION.json for current validation.

Previous release notes:
CURRENT: Academic 2026-10-20 r2. See the root README and Documentation/VALIDATION.json.
Package status/guidance corrected; nested loader and known-hash asset checks added.
The following r1 notes are historical baseline provenance, not the current validation tally.

PORTALAI ACADEMIC — 2026-10-20 r1

This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.

INSTALLERS
Windows: PortalAI-Academic-Windows-Installer-20261020-r1-x64.zip
SHA-256: c662f51a480d6049673e0ef32572c052c42a1715876ebfb638cdccbb4ff3583a

Linux: PortalAI-Academic-Linux-Installer-20261020-r1-x86_64.tar.gz
SHA-256: f42ae6d41838a67f016e16d66b79211224b13280751f3e336ae3ae9a5a9eb99f

Mac: PortalAI-Academic-Mac-Installer-20261020-r1-universal.tar.gz
SHA-256: dd6daea8d3edad6c2c1012a47cd0b5ba57ace22f7de8305814c73c104626b34d

Extract each archive into its own new folder on the desired drive.
Windows: run PortalAI-Academic-Install.exe. It creates PortalAI Windows and its launcher beside itself.
Linux x86-64: run sh install.sh. Default app folder: PortalAI Academic Linux.
Mac Apple silicon / Intel: run bash install-macos.sh. Default app folder: PortalAI Academic Mac.
Internet is required for pinned runtime/model downloads. Each installs the standard Qwen 1.7B chat model. Windows offers optional larger standard chat, vision and media components. Native packages retain their original platform scope; Mac requires Xcode Metal tools and CMake and remains unsigned/not notarized. Existing installation folders are refused.

ACADEMIC BEHAVIOR
- Standard/censored chat, vision and media selection is enforced in application code.
- Existing variant controls remain visible and inert; right-click/Control-click opens Academic help.
- Uncensored/abliterated models, anatomical LoRAs, DreamShaper, alternate Wan/FLUX assets and Portable Abliterator are excluded.
- Standard Klein4 encoder and VAE dependencies are retained. Standard 27B chat/vision is an optional Windows component.
- Agent/Academic_Instructions.txt (456 bytes) is appended to chat and mission instruction harnesses, including when the optional manual is disabled. The shared master instructions contain the appendix too; the compiled-in text survives a missing or altered sidecar.
- Original account, Stop, hardware, storage and workflow admission checks remain. Diagnostics may still name excluded optional assets.

VALIDATION
218 checks passed; one optional ACE vendor-source check skipped because that component is downloaded during installation. This comprises 15 Academic tests on each exact platform payload and 174 Windows regression tests (173 passed, one skipped). Tests include real Tk settings widgets, standard workflow routing, download guards, instruction assembly, account/Stop and context budgets. Final payload hashes, Windows component plans, shell syntax and the rebuilt Windows bundled-Python bootstrap passed. Linux/Mac Python checks used the Windows host; full recipient installs, physical Linux/Mac execution, live model refusals and generated-media acceptance were not tested.

CONTROLLED DEPLOYMENT
These are application restrictions and AI instructions, not an OS sandbox or a guarantee of model behavior. Staff should retain administrator credentials, use standard/guest student accounts, protect application files with OS permissions, and install only Academic updates. Standard media workflows retain their existing output-filtering capabilities.

SCOPE AND PROVENANCE
Based on the existing Windows r23 and Linux/Mac r13 public installer archives. Their hashes were rechecked unchanged. The existing D:\PortalAI Windows installation and original installer directories were not modified. Only this new Academic directory was added on D:. Source changes, build scripts and validation records are included.
