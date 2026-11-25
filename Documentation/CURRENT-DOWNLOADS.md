# Current PortalAI Academic downloads

[Back to downloads](../README.md#download-and-install)

Bundle **2026.11.25-bundle1** combines the latest available native installers and compatible optional utility files. These are complete distribution bundles, not complete offline model/runtime libraries.

| Choice | Application | Included optional companions |
| --- | --- | --- |
| [Windows](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle1/PortalAI-Academic-Windows-Bundle-2026.11.25-bundle1.zip) | r85, Windows x64 | Projection with 0.5.13 host update, Home Assistant 0.5.13 |
| [Mac](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle1/PortalAI-Academic-Mac-Bundle-2026.11.25-bundle1.zip) | Experimental r75, Apple silicon / Intel | Projection with 0.5.13 host update, Home Assistant 0.5.13 |
| [Linux](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle1/PortalAI-Academic-Linux-Bundle-2026.11.25-bundle1.zip) | Experimental r75, x86-64 | Projection with 0.5.13 host update, Home Assistant 0.5.13 |
| [All three OSes](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle1/PortalAI-Academic-Universal-Bundle-2026.11.25-bundle1.zip) | Windows r85; Mac/Linux r75 | All applicable companions |

## Install

Extract the entire ZIP into a new folder on an appropriate native filesystem: Windows NTFS, Mac APFS, Linux executable ext4. Keep **Packages**, **Utilities** and setup scripts together. Windows: open **Start Setup.cmd**. Mac: open **Start Setup.command** or run **bash prepare-setup.sh**. Linux: run **bash prepare-setup.sh**. Preparation verifies included native archives and asks before opening the installer for this OS.

Choose the destination and optional components in the native installer. Internet and enough disk/RAM/VRAM are still required for selected runtimes and models. [Detailed requirements](INSTALLATION.md). Universal carries all three native installers locally. Each OS performs its own native installation.

If already extracted, use the native installer's entry point under **Platforms**. Preparation refuses to overwrite an existing extraction folder.

## Optional companions

**You decide whether to install, configure or run them.** Native installer checkboxes and model policies are unchanged. Bundle preparation does not open Projection, install Abliterator, modify Home Assistant, pair a device or change an existing installation.

Companions are available at **Utilities / Windows**, **Utilities / Mac** or **Utilities / Linux**. Use the appropriate Projection launcher only if wanted and select the installed PortalAI folder. Use adjacent Home Assistant setup only for an existing HA instance you administer. The matching 0.5.13 host update is already included; no separate patch download is needed.

To expose these companions through PortalAI's Utilities page on a new installation, place **PortalAI-Projection** and **PortalAI HA Setup** together in **Utilities** beside the installed application. For an existing companion, preserve **Connections** and **state** and follow the [guarded upgrade guide](RELEASE-HA-0.5.13.md); do not overwrite personalized folders.

Academic excludes Portable Abliterator and Full-only model assets. This bundle does not change its standard-only policy.

Windows reset and Weight-Space Editor launchers remain in the native payload where supported. Use them from the installed application's Utilities. Reset can delete local data; use its own confirmation and instructions.

[Projection pairing and platform requirements](PROJECTION.md)

## Existing installations

Exit PortalAI normally and allow account sealing to finish. Windows offers **Update existing**; Mac/Linux native installers accept an existing destination with **--upgrade**. Preserve accounts, models, outputs, credentials and settings. [Upgrade and recovery workflow](UNIFIED-20261025-r45.md#updating-an-existing-installation).

## Latest changes and verification

This refresh changes packaging and documentation. The verified Windows r85 and Mac/Linux r75 native archives are included byte for byte. Optional selections and model/runtime pins are unchanged. Fresh companions receive the published 0.5.13 host changes after verifying the reviewed baseline, together with the published HA 0.5.13 integration.

- [Windows r85 changes and validation](RELEASE-r85.md)
- [Mac/Linux r75 baseline](RELEASE-r75.md)
- [Home Assistant 0.5.13 changes and limits](RELEASE-HA-0.5.13.md)
- [Whole-download checksums](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle1/SHA256SUMS.txt)
- [Bundle manifest and build validation](DOWNLOAD-BUNDLES.json)
- [Older release history and tracked changes](RELEASE-HISTORY.md)

Each bundle contains **bundle.json**, **BUNDLE-CONTENTS.json** and **SHA256SUMS**. Preparation verifies native archive sizes and SHA-256 digests. **-VerifyOnly** (PowerShell) or **--verify-only** (Bash) verifies without launching; **-ExtractOnly** / **--extract-only** extracts without launching. Whole-bundle hashes are published separately.

Windows has received extensive runtime testing. Linux/macOS are experimental and remain behind Windows; packaging checks are not fresh native installations or live inference tests. Phone microphone and voice acceptance limits remain those in the 0.5.13 release.
