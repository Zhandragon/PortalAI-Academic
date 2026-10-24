# PortalAI Projection and Home Assistant

[Documentation index](README.md) · [Downloads and overview](../README.md#projection-and-home-assistant)

Projection is an optional portable companion to the PortalAI application. It connects the real running interface to your Home Assistant (HA) dashboard and Companion App over an outbound, verified HTTPS connection. Models still run on the PortalAI host. This remote feature sends interface state, screen frames and control requests through HA; it is not an offline-only workflow.

**macOS Projection is now packaged for Intel and Apple silicon (macOS 14+); native Mac acceptance remains pending.** Install the companion for the computer running PortalAI, not the phone, tablet or computer used to view Home Assistant.

## Host requirements and downloads

| Host | Support and download |
| --- | --- |
| Windows x64 | [Windows Projection setup](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-Projection-Windows-Setup.exe). An unlocked, signed-in desktop is required. The downloader needs .NET Framework 4.5+, included with Windows 10/11. |
| Linux x86-64 | [Linux Projection setup](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-Projection-Linux-Setup.sh). Requires Linux 5.14+, an unlocked X11/XWayland TrueColor desktop, a drive mounted with execution allowed, and a delegated cgroup v2 with memory control. The launcher requests a systemd user scope without sudo. Download setup uses Bash, curl, tar and SHA-256 utilities. |
| macOS 14+, Intel / Apple silicon | [Mac Projection + HA setup](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.24-r7/PortalAI-Projection-Mac-20261024-r7.tar.gz). Bundled runtime, verified owned-window capture and separate recovery. Physical Mac acceptance pending. |

Linux has partial validation; physical Linux desktops remain unvalidated. ARM Linux, headless/locked desktops, native Wayland without XWayland, missing cgroup delegation and unusual visual formats are unsupported. Physical HA Green/Home Assistant Cloud deployment has not been validated end to end. Report problems to the [maintainer](https://github.com/Zhandragon/PortalAI-Academic/issues) with OS versions and the error message, excluding passwords, tokens and private connection files.

## Mac setup

Extract the Mac bundle and keep its two Utilities folders together, outside the main PortalAI account root. Open `Start Projection.command`, select the installed PortalAI folder containing `PortalAI.app`, and grant Screen Recording permission for desktop projection. Use `Install PortalAI HA.command` in the sibling HA setup folder. Existing compatible hosts can use the separately guarded `Update PortalAI Mac Host.command` with PortalAI closed. Read [Mac setup](MacProjection/SETUP.txt) for prerequisites and limitations.

## 1. Prepare the companion

Install PortalAI first. Open the Windows download, or on Linux run:

```sh
bash PortalAI-Projection-Linux-Setup.sh
```

Choose a new folder on the **same drive** as the installed PortalAI application. The downloader verifies every part, reconstructs the archive, checks extracted files and opens the companion. Its `utilities` folder contains two sibling folders: `PortalAI-Projection` and `PortalAI HA Setup`. Keep them together. Python/Tk/TLS dependencies are included; no host Python or Node installation is required for these companion launchers.

For later launches, use `utilities/PortalAI-Projection/Start Projection.cmd` on Windows or `sh "utilities/PortalAI-Projection/Start Projection.sh"` on Linux. The setup downloader is for preparing/verifying the distribution; you do not need to redownload it each time.

## 2. Set your Home Assistant link and PortalAI folder

In Projection, supply:

- A connection name of your choice.
- Your Home Assistant **HTTPS origin**, for example `https://YOUR-INSTANCE.ui.nabu.casa`. Use the scheme and hostname, with an optional port, but no dashboard path, query, fragment or embedded credentials. Your own trusted HTTPS HA origin is also supported. The companion does not accept plain HTTP or bypass TLS verification, even though the HA web interface itself can support local HTTP.
- The actual **PortalAI Academic application folder**. Browse to the folder containing `PortalAI.exe` on Windows or `PortalAI.sh` on Linux, together with `Agent/profile_shutdown.py`. Do not select a download folder or rely on the suggested sibling path when your installation has a different name.
- A new **projection unlock password of at least 12 characters**. This is separate from your PortalAI account and HA password.

Click **Create / Unlock**. Copy the displayed public pairing JSON and its public `device_id`. The companion also writes a `.public-pairing.json` export under `Connections`. Only that public export is needed on the HA side. The encrypted `.enc` connection file stays with your companion.

Use Home Assistant's own sign-in on a trusted device. The Projection connection manager does not accept an HA password or API token. Your HTTPS link must reach the installed custom endpoints; the link alone cannot install the receiver or grant approval.

## 3. Install the matching Home Assistant integration

The bundle includes **PortalAI Home Assistant 0.5.12 + Recovery 0.1.0**. HA must already be installed, onboarded and accessible to its administrator. Back up its configuration, then use a writable HA configuration folder or share.

**From Windows:** open `utilities/PortalAI HA Setup/Install PortalAI HA.cmd`. Choose **Install** for a writable config/share, or **Prepare** to create a deployment ZIP for a trusted HA device. Enter the public device ID generated above. This uses the sibling companion's bundled Python.

**From Linux:** run the included launcher from a terminal:

```sh
sh "utilities/PortalAI HA Setup/Install PortalAI HA.sh"
```

It uses the companion's bundled Linux Python and asks for the writable HA configuration path and public device ID. It does not install Home Assistant OS or configure remote access.

**Directly on a trusted HA device:** download and extract the [matching integration ZIP](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-HomeAssistant-0.5.11-recovery-0.1.0.zip), verify its [SHA-256](../Utilities/Projection/PortalAI-HomeAssistant-0.5.11-recovery-0.1.0.zip.sha256), enter the extracted `HomeAssistant` folder and run `sh install.sh`. This direct route needs Python 3.9+ on that device. Read its `README_FIRST.txt` before installation.

For standard HA layouts the installer adds the integrations and frontend modules, a PortalAI Native sidebar, and Quick Chat/Desktop/Recovery dashboard views. Changed files receive verified backups. Advanced YAML layouts with external includes, packages, aliases or conflicting dashboards stop before automatic writes; follow the package's explicit `--files-only` and manual-merge instructions.

Check the HA configuration, restart HA normally, then reload the browser/Companion App. The installer optionally offers an HA URL and a private administrator-token prompt for automatic validation/restart and initial pairing. That token is only used in memory on the trusted installer device; leave this option blank to finish inside HA manually. No HA credentials belong in the Projection connection manager or in this repository.

## 4. Approve your device

If the installer's optional first-pairing flow already succeeded, do not pair the device again. Otherwise, signed into HA as an administrator, open **Developer Tools > Actions**:

1. Run `portalai_projection.pair_device`, pasting the complete **public pairing JSON** into `pairing_request`.
2. Run `portalai_native.allow_state` with the same public `device_id` to allow the Native UI's read-only state channel. Projection pairing alone does not grant this separate scope.

These approvals are specific to that HA instance. They do not give the companion general HA API access. Existing approvals are preserved during installation. A different destination needs its own installation and pairing.

## 5. Start PortalAI and view it in HA

Click **Start projection**, then **Open PortalAI locally** in the companion. Sign in through PortalAI's real account screen. Open the **PortalAI Native** sidebar or the installed Desktop/Quick Chat dashboard in HA or the HA Companion App. If an existing custom card is used, set its `device_id` to your public ID; the companion shows example YAML.

Close an already-running PortalAI normally before reopening it through the companion when its input/native-state adapters are missing. This is required on Linux for the owned-window capture path. The Academic application's restrictions and normal account permissions continue to apply.

Desktop projection streams PortalAI's windows, not arbitrary desktop applications. It does not forward the operating-system clipboard, microphone or audio. The Native UI offers supported file/media controls separately. Availability depends on the installed host and matching receiver versions. There is one shared PortalAI desktop login and one active HA viewer at a time.

## Stop, move or change a connection

**Stop projection does not sign out of PortalAI or seal its user workspace.** Use PortalAI's normal Accounts/Exit controls and wait for shutdown to finish before disconnecting the drive. The host must remain awake, its drive connected and its desktop unlocked while projecting.

To change the HA link or application folder, stop projection, wait for the worker to exit, unlock the saved connection, edit and **Save changes**. Paths are saved relative to the companion so a changed Windows drive letter can be accommodated when both folders remain on the same drive. Remove a retired device through `portalai_projection.remove_device` and revoke its separate native-state scope with `portalai_native.revoke_state` as appropriate.

Connections use AES-GCM encryption with a password-derived scrypt key for the URL, relative application path and projection device key. This protects stored files; it is not isolation from software running as the same OS user while unlocked. No existing connection, pairing, account, screen capture or runtime state is distributed here.

## Optional Windows/Mac recovery

`Start HA Recovery.cmd` on Windows and `Start HA Recovery.command` on Mac are separate recovery helpers. It needs its own explicit pairing and local arming; ordinary Projection pairing does not enable recovery. Follow the included `PortalAI HA Setup/Setup Files/HomeAssistant/RECOVERY.txt`. It can assist with application crashes while the operating system, helper and storage remain available; it does not repair an OS crash or a disconnected drive. It is optional for normal projection.

## Package verification

The setup files embed the expected SHA-256 hashes for the downloaded parts, reconstructed archive and extracted files. [Packaging metadata and source](../Utilities/Projection/) are published alongside them. Every repository file stays below the browser upload size limit; launchers retrieve and join the parts automatically. Current Mac installer packages include the companion; Windows/Linux standalone downloads retain their previously published versions.

Projection UI 20261022-r1: minimize to the dark emblem; click to reopen. Right-click the tray or inside the launcher for themed actions and help. Appearance and Documentation are built in. Keep Connections/ and state/ when updating. Native Mac/Linux tray acceptance remains pending.
