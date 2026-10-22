<p align="center">
  <img src="Documentation/assets/portalai-logo.png" width="100" alt="PortalAI gold and blue portal emblem" />
  &nbsp;&nbsp;
  <img src="Documentation/assets/portalai-wordmark.png" width="340" alt="PortalAI wordmark" />
</p>

<h1 align="center">PortalAI</h1>

<p align="center"><sub>(Academic)</sub></p>

<p align="center"><strong>Local AI for guided learning and classroom exploration.</strong></p>

<p align="center">
  <a href="#download-and-install">Download</a> &nbsp;·&nbsp;
  <a href="#a-look-inside">Interface gallery</a> &nbsp;·&nbsp;
  <a href="#built-in-help-and-documentation">Help</a> &nbsp;·&nbsp;
  <a href="#projection-and-home-assistant">Projection / Home Assistant</a> &nbsp;·&nbsp;
  <a href="#companion-utilities">Utilities</a> &nbsp;·&nbsp;
  <a href="Documentation/README.md">Documentation</a>
</p>

**Welcome to PortalAI:** a portable workspace for local chat, tools, science, images, video, speech and music.

> This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.

The Academic edition keeps PortalAI's main interface and supported workflows, with standard/censored chat, vision and media enforced. Variant controls remain visible but inert, excluded model and LoRA assets are not downloaded, and an Academic instruction appendix is applied to the chat and mission harnesses.

**Unrestricted distribution — by special request and approval only.**

The unrestricted version of PortalAI is currently private to prevent misuse. To request access to the abliterated/uncensored PortalAI distribution repository, please contact genesislung@gmail.com

> **Platform testing disclaimer:** Only Windows has been thoroughly tested. Linux has received partial validation; macOS and other operating systems have not been thoroughly tested. Installation may fail or other errors may occur on these platforms. Please [report problems to the maintainer](https://github.com/Zhandragon/PortalAI-Academic/issues), including your operating system version and the error message. Packaging checks are not fresh end-to-end inference tests on all three operating systems.

**PortalAI runs its AI locally on your computer.** Models, inference, supported tools, conversation history and account storage live on your own host and drive; core use requires no hosted AI service or cloud API key. After the required components are installed, supported local workflows can run offline. Installation and model downloads need internet access, and optional web tools and Home Assistant projection use the network you choose. Remote projection sends interface data through your Home Assistant connection while AI inference stays on the PortalAI host.

- **Dynamic VRAM loading and offloading.** Models and media workers load on demand. Memory admission checks and exclusive GPU leases let supported heavy workflows release the chat model's VRAM, run their work, then restore chat. Model/backend choices account for available hardware; this manages limited memory rather than removing hardware requirements.
- **Rolling memory compaction.** Long tasks checkpoint completed tool exchanges into compact working notes while keeping the current request, recent complete exchanges and important results and file paths. The retained transcript can be searched for exact details, helping work continue beyond one context window without pretending everything remains in active context.
- **Persistent missions and schedules.** Save an objective, access settings and an action budget, or configure scheduled work. Missions must be armed and schedules enabled explicitly; Stop/Exit pauses future work. Execution needs PortalAI running, an awake host and the drive connected.
- **A compact tool and multimedia harness.** Short default instructions, targeted tool schemas and runtime-managed media steps reduce repeated catalog searches and model deliberation. The harness handles details such as media timing and frame calculations and carries results forward through compaction. This is designed to reduce planning overhead; performance still depends on the model and workflow.
- **Local accounts and encrypted user vaults.** Password-protected accounts use password-derived keys and authenticated encryption for stored profile keys and sealed user workspaces. Workspace files are decrypted while an account is in use; normal Exit seals them again. Guest is a shared/public workspace, and encryption is not isolation from the signed-in operating-system user.
- **Context-aware help and a nonintrusive interface.** Right-click controls for relevant actions and built-in help. Switch between the full workspace and Compact chat, or keep PortalAI reachable through the Windows notification icon while the window is hidden.


**New: web tools, collaborating agents, configurable ports and Mac Projection.** See the [feature update](Documentation/UPDATE-20261021.md). Full and Academic installers keep separate model policies.

**Latest fix: silent background web tools.** [Release details and checks](Documentation/SILENT-WEB-20261021.md). Restart normally after updating an existing installation.

## Download and install

<a id="download-an-installer"></a>

Download **one file for your operating system**. The launcher downloads its pinned complete installer from this repository’s GitHub release, verifies the archive and extracted files, and starts the Academic installation. Older downloaded launchers can still use their original retained package parts.

| Operating system | Download | Open it |
| --- | --- | --- |
| Windows x64 | [Windows installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Windows-Setup.exe) | Open the `.exe`, choose the setup location, and click **Download and install**. Continue in the full installer window. |
| Linux x86-64 | [Linux installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Linux-Setup.sh) | Save the file, then run `bash PortalAI-Academic-Linux-Setup.sh` in its download folder. |
| macOS, Apple silicon / Intel | [Mac installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Mac-Setup.zip) | Extract the ZIP and open **PortalAI Academic Installer.app**. Terminal opens for setup. |

Use the download links above, or the file page's **Download raw file** button. You do not need **Code > Download ZIP**. Linux browsers generally do not preserve the executable bit, so running the file with Bash avoids that extra step.

<a id="setup"></a>

Choose a new setup folder on the drive where PortalAI should live. Windows installs under that folder's `installer/PortalAI Windows`; Linux and Mac install in `PortalAI Academic Linux` or `PortalAI Academic Mac` beneath the chosen setup folder. Existing application folders are not overwritten.

The first stage downloads approximately 344 MB (Windows), 557 MB (Linux), or 680 MB (Mac). The full installers then fetch their pinned runtime/model dependencies; actual storage and download requirements are larger. Keep the setup folder on a drive with sufficient space. Verified downloads are reused if setup is run again.

Windows needs .NET Framework 4.5 or later, included in Windows 10/11. Linux and Mac need Bash, curl, tar, and a SHA-256 utility, usually supplied by the operating system. No host Python installation is needed. The Mac installer retains its existing Xcode/Metal toolchain and CMake requirements. These installers are unsigned; macOS or Windows may require the normal user approval to open a downloaded application. Do not disable OS security protections.

The original Academic restrictions and platform requirements are described in [the build documentation](Documentation/README.txt). These launchers reconstruct their pinned release archives byte-for-byte. They only automate download, verification, reconstruction, extraction and installer startup.

## A look inside

**Welcome to PortalAI.** The Control Center brings navigation, chat, runtime information and settings into one interface.


[![PortalAI welcome panel with the original gold wordmark, blue portal emblem and navigation tabs](Documentation/assets/welcome-panel.jpg)](Documentation/assets/welcome-panel.jpg)

**Chat.** The full chat workspace includes conversation history, attachments, effort controls and the original gold window borders.

[![PortalAI Chat in the complete Control Center window, showing an illustrative classroom conversation](Documentation/assets/chat-panel.jpg)](Documentation/assets/chat-panel.jpg)

**Compact chat bar.** A nonintrusive view keeps chat controls nearby while you work in other applications. Use **View > Full UI** to return to the Control Center.

[![PortalAI compact chat bar with its original branding, border, attachment field and chat controls](Documentation/assets/compact-chat-bar.jpg)](Documentation/assets/compact-chat-bar.jpg)

**Context-aware right-click help.** Menus adapt to the control or panel you click, combining relevant actions with a direct link to its built-in help topic. The settings example below offers hardware-fit checks, settings actions and **Help: Settings · chat and media**.

[![The original Chat model right-click menu showing settings actions and context-sensitive help](Documentation/assets/context-help-menu.jpg)](Documentation/assets/context-help-menu.jpg)

**Minimize to the Windows tray.** Use **Controls > Minimize to tray** or the title-bar tray button to hide the Control Center while work continues. The notification icon remains available (Windows may place it under the overflow chevron). Click it to restore the window, or right-click for navigation, help, theme and lifecycle actions. **Minimizing does not sign out, seal the workspace or stop jobs**; use **Exit PortalAI** for normal shutdown. If the tray icon cannot be created, PortalAI falls back to the taskbar. This notification-area behavior is Windows-specific.

| Minimize control and its help | Notification-icon menu |
| --- | --- |
| [![Minimize to tray with its focused Tray icon help menu](Documentation/assets/tray-controls.jpg)](Documentation/assets/tray-controls.jpg) | <a href="Documentation/assets/tray-menu.jpg"><img src="Documentation/assets/tray-menu.jpg" width="230" alt="PortalAI notification-icon menu with restore, navigation, help and lifecycle actions" /></a> |

**Runtime and Packages.** Runtime brings CPU, RAM, GPU and VRAM activity, owned-process information and reported model stages into one read-only panel. Packages provides a searchable, paginated capability inventory and installation status. Academic restrictions still apply even when the diagnostic catalog mentions an unavailable component. Intentionally omitted models are labeled **EXCLUDED**.

| Runtime monitoring | Package inventory |
| --- | --- |
| [![Runtime panel with illustrative CPU, RAM, GPU and VRAM telemetry](Documentation/assets/runtime-panel.jpg)](Documentation/assets/runtime-panel.jpg) | [![Packages panel showing capability descriptions and installation status in the isolated preview](Documentation/assets/packages-panel.jpg)](Documentation/assets/packages-panel.jpg) |

**Hardware scaling with manual control.** Automatic selection fits eligible installed models to available RAM/VRAM and selects a compatible backend. Settings also lets you choose a model, backend, context limit and supported media defaults explicitly. **Check hardware fit** previews the choice. Manual overrides still have to pass hardware and memory admission checks. Backend, context and media changes use **Save settings**; **Controls > Startup** applies chat settings when active work permits. The Academic chat, vision and media variant remains fixed to standard.

| Chat model and memory | Media defaults |
| --- | --- |
| [![Academic chat settings in the complete Control Center window, showing the standard variant, backend, context limit and vision routing](Documentation/assets/chat-model-settings.jpg)](Documentation/assets/chat-model-settings.jpg) | [![Academic media settings in the complete Control Center window, with standard mode enforced](Documentation/assets/media-defaults.jpg)](Documentation/assets/media-defaults.jpg) |
| Choose model, memory and backend preferences while the Academic variant stays fixed to standard. | Review the defaults for supported media workflows and their hardware requirements. |

<sub>Windows screenshots of the Academic build's real widgets in Light mode, captured in an isolated preview. Chat and Runtime telemetry are illustrative; package status reflects the preview's incomplete runtime inventory. The original tray menu is opened by a capture-only shortcut. Available workflows depend on the operating system and installed components. Click a panel to view it at full size. See the <a href="Documentation/assets/README.md">artwork notes</a> for capture details.</sub>

## Built-in help and documentation

**Documentation and help are already included in PortalAI.** Open the **Help** tab in the Control Center to browse topics by category or search the built-in documentation. Right-click controls for context-sensitive help, or choose **Documentation / Help** from the context menu. The included help is available offline after installation; no separate documentation download is needed.

The [documentation index](Documentation/README.md) links installation, Projection, release validation and artwork notes. When reporting a problem to the maintainer, include the operating system version, installer/release version and exact error text; leave out passwords, tokens and private account or connection files.

## Projection and Home Assistant

The optional **PortalAI Projection** companion brings the running PortalAI interface to your Home Assistant dashboard or Companion App. Chat and model execution stay on the PortalAI computer; Home Assistant provides the remote viewing and control connection. Select your installed Academic folder to retain its Academic restrictions.

> **macOS Projection is now packaged for Intel and Apple silicon (macOS 14+); native Mac acceptance remains pending.** The companion is available for Windows x64, Linux x86-64 and macOS 14+; the Mac package is also included beside the Academic Mac installer. Linux has partial validation and requires an unlocked X11/XWayland desktop, Linux 5.14+, an executable drive and delegated cgroup v2 memory control through a systemd user scope. Physical Linux desktops and end-to-end Home Assistant Cloud deployment have not been validated.

| Projection host | Download | Open it |
| --- | --- | --- |
| Windows x64 | [Projection for Windows](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-Projection-Windows-Setup.exe) | Open the `.exe` and choose a new folder on the same drive as PortalAI. |
| Linux x86-64 | [Projection for Linux](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-Projection-Linux-Setup.sh) | Run `bash PortalAI-Projection-Linux-Setup.sh` from a supported graphical desktop. |
| macOS 14+, Intel / Apple silicon | [Mac Projection + HA setup](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.21-r2/PortalAI-Mac-Projection-HA-20261021-r1.tar.gz) | Extract, open `Utilities/PortalAI-Projection/Start Projection.command`; use `Utilities/PortalAI HA Setup/Install PortalAI HA.command` for HA setup. |

Each download reconstructs and verifies its complete portable companion, bundled Python runtime and matching **Home Assistant 0.5.11 + Recovery 0.1.0** integration package. No host Python or Node installation is needed for the companion. The packages contain no saved connections, pairing identities or user accounts.

1. Download the companion for the **computer running PortalAI**. In Projection, enter your Home Assistant **HTTPS link/origin**, browse to the actual installed PortalAI Academic folder, and create a separate projection unlock password of at least 12 characters. Click **Create / Unlock** to generate your public pairing request.
2. Install the included **PortalAI HA Setup** package into your existing Home Assistant configuration from a trusted administrator device. Home Assistant must already be installed and onboarded; a URL alone does not install its integration. Use the public device ID from step 1, check the HA configuration, restart HA and reload its browser/app.
3. In HA **Developer Tools > Actions**, run `portalai_projection.pair_device` with the public JSON in `pairing_request`. For the Native UI, also run `portalai_native.allow_state` with your `device_id`. The installer's optional first-pairing flow can perform both approvals.
4. Click **Start projection**, then **Open PortalAI locally** in the companion. Sign in to PortalAI and open the PortalAI Native sidebar or Desktop/Quick Chat dashboard in Home Assistant.

See the [complete Projection and Home Assistant guide](Documentation/PROJECTION.md) for Windows/Linux/Mac installation, HTTPS link requirements, pairing, troubleshooting and the difference between stopping projection and signing out. For installation directly on a trusted HA device, the [matching HA integration ZIP](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-HomeAssistant-0.5.11-recovery-0.1.0.zip) is also available separately.

## Companion utilities

| Utility | Downloads and purpose |
| --- | --- |
| PortalAI Projection | Windows, Linux and Mac companions for viewing and controlling PortalAI through Home Assistant. [Downloads and connection steps](#projection-and-home-assistant). **macOS Projection is now packaged for Intel and Apple silicon (macOS 14+); native Mac acceptance remains pending.** |
| Home Assistant integration | Matching **Home Assistant 0.5.11 + Recovery 0.1.0** receiver/frontend bundle, included with Projection and [available separately](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-HomeAssistant-0.5.11-recovery-0.1.0.zip). |

Portable Abliterator and the excluded uncensored model assets are not part of the Academic distribution. Use the supported components supplied for your operating system.

## Privacy and local accounts

This repository provides the public Academic installer distribution. Recipients create their own PortalAI accounts and Projection pairings; the download is not a copy of the maintainer's active personal workspace.

Password-protected accounts encrypt stored user vaults. Files are decrypted while that account is in use and sealed on normal **Exit PortalAI**. **Minimize to tray** and **Stop projection** do not sign out or seal the workspace. Guest is shared, and unlocked data remains accessible to software with the same operating-system access. Keep the host and drive available until shutdown completes.

## Antivirus and the llama.cpp server

Antivirus software may flag or quarantine PortalAI's llama.cpp local model server (`llama-server.exe` on Windows), its supporting libraries, bundled runtimes or the unsigned launcher. This can prevent chat models or workflows from starting and cause local server connection errors. A detection is not by itself proof of either malware or a false positive.

Check the blocked file's path and detection name, verify its source and expected SHA-256 checksum, and review the alert before restoring it or approving a specific file exception. Students should ask their instructor or IT administrator to review the alert. Do not disable antivirus globally or exclude the entire PortalAI folder. Include the antivirus product and detection name in a report to the maintainer, without submitting private data.

## Source, licensing and verification

- The three setup downloads and their checksums are at the repository root.
- `PACKAGING.json` pins the current GitHub release assets and extracted files. `packages/` retains prior parts for previously downloaded launchers.
- `Documentation/` contains the Academic build details, source changes, validation records and interface artwork.
- `bootstrap-source/` contains the online launcher source and build instructions.
- `Utilities/Projection/` contains the optional Windows/Linux Projection downloads, verified package parts, matching Home Assistant integration and source. [Mac Projection + HA setup](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.21-r2/PortalAI-Mac-Projection-HA-20261021-r1.tar.gz) is now available; native acceptance is pending.

Maintainers can follow [the publishing guide](Documentation/PUBLISHING.md) to update this repository. Students only need the download for their operating system above.

`PACKAGING.json` records the pinned part, reconstructed archive and extracted installer hashes. `SHA256SUMS` covers the published files. The launchers embed the expected hashes and do not trust a downloaded manifest to decide what code to run.

Maintainers can rebuild the launchers on Windows with Python 3.11+ and the .NET Framework C# compiler:

```text
python -B bootstrap-source/build.py
```

The native installer template is compatible with macOS Bash 3.2. `--prepare-only` plus a target directory allows download/extraction verification without starting an installation. See `bootstrap-source/VALIDATION.txt` for validation scope and commands.

PortalAI's existing [license](LICENSE) is retained. Third-party runtime and model licenses remain separate and travel with the relevant packages; this distribution does not replace their terms.

## Release notes

### Current: web tools, agents, ports and Mac projection

See [the silent web fix](Documentation/SILENT-WEB-20261021.md) and [its checks](Documentation/SILENT-WEB-VALIDATION.json). The [feature release notes](Documentation/UPDATE-20261021.md) and [earlier publication checks](Documentation/PUBLISH-VALIDATION.json) remain available. The earlier records below describe the release baseline.


**2026-10-21 r1 — welcome access notice.** The GitHub welcome page and Academic GUI now explain that the unrestricted repository is private and provide the maintainer's access-request email. In the GUI, the notice appears in small, theme-aware text below the feature tagline and wraps with the window width. Academic model restrictions and runtime behavior remain as in r2.

The Windows, Linux and Mac installer packages were rebuilt and their archive/member hashes verified. Only the welcome UI source and Academic documentation changed inside each application payload; every other payload file matches r2. The real Windows welcome panel was checked in Light and Dark modes, including a narrower window. Native Linux/macOS installation and model inference were not rerun. [Current validation](Documentation/VALIDATION.json) · [Source changes](Documentation/PortalAI-Academic-Source-Changes-20261021-r1.zip).

Download a current setup launcher above and use a fresh setup folder to receive this update. Older launchers remain pinned to their original packages, whose parts are retained. Existing installations are not automatically patched.

**Previous release: 2026-10-20 r2.**

<a id="academic-maintenance-release-r2"></a>

The r2 maintenance update labels intentionally omitted models **EXCLUDED** rather than leaving their package rows checking indefinitely. Tool discovery, mission instructions and settings help now consistently describe standard-only routing. Workflow admission checks nested/multiple model and LoRA loader fields, including encoded names; installer/import guards also reject known excluded asset hashes even when their labels are changed. Ordinary prompt prose is not treated as an asset filename.

These are Academic-only changes. They do not add a media output classifier or an operating-system security boundary. No crash caused by intentionally removed alternate weights was reproduced in the checks. Standard dependencies, platform support and memory admission still determine whether a requested workflow can run.

The r2 checks passed 23 Academic tests per platform payload, plus the 174-test Windows regression suite (173 passed, one optional vendor-source check skipped). Linux/Mac source tests ran on Windows; physical recipient installs and model inference were not rerun. [r2 validation](Documentation/VALIDATION-20261020-r2.json) · [r2 source changes](Documentation/PortalAI-Academic-Source-Changes-20261020-r2.zip).

The r2 release changed new installation packages and did not modify an existing personal installation. Its policy and regression checks remain the baseline for subsequent updates.
