<p align="center">
  <img src="Documentation/assets/portalai-logo.png" width="100" alt="PortalAI gold and blue portal emblem" />
  &nbsp;&nbsp;
  <img src="Documentation/assets/portalai-wordmark.png" width="340" alt="PortalAI wordmark" />
</p>

<h1 align="center">PortalAI Academic</h1>

<p align="center"><strong>Local AI for guided learning and classroom exploration.</strong></p>

<p align="center">
  <a href="#download-an-installer">Download</a> &nbsp;·&nbsp;
  <a href="#a-look-inside">Interface gallery</a> &nbsp;·&nbsp;
  <a href="Documentation/README.txt">Academic guide</a> &nbsp;·&nbsp;
  <a href="#antivirus-and-the-llamacpp-server">Antivirus help</a>
</p>

> This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.

## Download an installer

Download **one file for your operating system**. The launcher downloads its required package parts from this repository, checks their sizes and SHA-256 hashes, reconstructs the full installer, and starts the Academic installation. You do not need to download or join parts yourself.

| Operating system | Download | Open it |
| --- | --- | --- |
| Windows x64 | [Windows installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Windows-Setup.exe) | Open the `.exe`, choose the setup location, and click **Download and install**. Continue in the full installer window. |
| macOS, Apple silicon / Intel | [Mac installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Mac-Setup.zip) | Extract the ZIP and open **PortalAI Academic Installer.app**. Terminal opens for setup. |
| Linux x86-64 | [Linux installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Linux-Setup.sh) | Save the file, then run `bash PortalAI-Academic-Linux-Setup.sh` in its download folder. |

Use the download links above, or the file page's **Download raw file** button. You do not need **Code > Download ZIP**. Linux browsers generally do not preserve the executable bit, so running the file with Bash avoids that extra step.

## A look inside

**Welcome to PortalAI.** The Control Center brings navigation, chat, runtime information and settings into one interface.

[![PortalAI welcome panel with the original gold wordmark, blue portal emblem and navigation tabs](Documentation/assets/welcome-panel.jpg)](Documentation/assets/welcome-panel.jpg)

**Chat.** The full chat workspace includes conversation history, attachments, effort controls and the original gold window borders.

[![PortalAI Chat in the complete Control Center window, showing an illustrative classroom conversation](Documentation/assets/chat-panel.jpg)](Documentation/assets/chat-panel.jpg)

**Compact chat bar.** Keep the compact controls nearby, then use **View > Full UI** to return to the Control Center.

[![PortalAI compact chat bar with its original branding, border, attachment field and chat controls](Documentation/assets/compact-chat-bar.jpg)](Documentation/assets/compact-chat-bar.jpg)

| Chat model and memory | Media defaults |
| --- | --- |
| [![Academic chat settings in the complete Control Center window, showing the standard variant, backend, context limit and vision routing](Documentation/assets/chat-model-settings.jpg)](Documentation/assets/chat-model-settings.jpg) | [![Academic media settings in the complete Control Center window, with standard mode enforced](Documentation/assets/media-defaults.jpg)](Documentation/assets/media-defaults.jpg) |
| Choose model, memory and backend preferences while the Academic variant stays fixed to standard. | Review the defaults for supported media workflows and their hardware requirements. |

<sub>Windows screenshots of the Academic build's complete Control Center and its compact mode. The chat conversation is illustrative; settings use sample inventory. Available workflows depend on the operating system and installed components. Click a panel to view it at full size. See the <a href="Documentation/assets/README.md">artwork notes</a> for capture details.</sub>

## Setup

Choose a new setup folder on the drive where PortalAI should live. Windows installs under that folder's `installer/PortalAI Windows`; Linux and Mac install in `PortalAI Academic Linux` or `PortalAI Academic Mac` beneath the chosen setup folder. Existing application folders are not overwritten.

The first stage downloads approximately 88 MB (Windows), 128 MB (Linux), or 102 MB (Mac). The full installers then fetch their pinned runtime/model dependencies; actual storage and download requirements are larger. Keep the setup folder on a drive with sufficient space. Verified downloads are reused if setup is run again.

Windows needs .NET Framework 4.5 or later, included in Windows 10/11. Linux and Mac need Bash, curl, tar, and a SHA-256 utility, usually supplied by the operating system. No host Python installation is needed. The Mac installer retains its existing Xcode/Metal toolchain and CMake requirements. These installers are unsigned; macOS or Windows may require the normal user approval to open a downloaded application. Do not disable OS security protections.

The original Academic restrictions and platform requirements are described in [the build documentation](Documentation/README.txt). These launchers preserve the original installer archives byte-for-byte. They only automate download, verification, reconstruction, extraction and installer startup.

## Antivirus and the llama.cpp server

Antivirus software may flag or quarantine PortalAI's llama.cpp local model server (`llama-server.exe` on Windows) or its supporting libraries. This can prevent chat models from starting or cause local server connection errors. False positives have been reported for [upstream llama.cpp Windows builds](https://github.com/ggml-org/llama.cpp/issues/15874).

If this happens, check your antivirus protection history for the blocked file's path and detection name. Ask your instructor or IT administrator to review the alert and verify the file's source and expected checksum before restoring it or approving a specific file exception. Do not disable antivirus protection or exclude the entire PortalAI folder; an alert should be reviewed before treating it as a false positive.

## Repository contents

- The three setup downloads and their checksums are at the repository root.
- `packages/20261020-r1/` contains the verified package parts, grouped by operating system. The launchers download these automatically.
- `Documentation/` contains the Academic build details, source changes, validation records and interface artwork.
- `bootstrap-source/` contains the online launcher source and build instructions.

Maintainers can follow [the publishing guide](Documentation/PUBLISHING.md) to update this repository. Students only need the download for their operating system above.

## Build and verification

`PACKAGING.json` records the pinned part, reconstructed archive and extracted installer hashes. `SHA256SUMS` covers the published files. The launchers embed the expected hashes and do not trust a downloaded manifest to decide what code to run.

Maintainers can rebuild the launchers on Windows with Python 3.11+ and the .NET Framework C# compiler:

```text
python -B bootstrap-source/build.py
```

The native installer template is compatible with macOS Bash 3.2. `--prepare-only` plus a target directory allows download/extraction verification without starting an installation. See `bootstrap-source/VALIDATION.txt` for validation scope and commands.
