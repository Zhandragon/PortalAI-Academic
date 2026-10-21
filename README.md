# PortalAI Academic

This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.

## Download an installer

Download **one file for your operating system**. The launcher downloads its required package parts from this repository, checks their sizes and SHA-256 hashes, reconstructs the full installer, and starts the Academic installation. You do not need to download or join parts yourself.

| Operating system | Download | Open it |
| --- | --- | --- |
| Windows x64 | [Windows installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Windows-Setup.exe) | Open the `.exe`, choose the setup location, and click **Download and install**. Continue in the full installer window. |
| macOS, Apple silicon / Intel | [Mac installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Mac-Setup.zip) | Extract the ZIP and open **PortalAI Academic Installer.app**. Terminal opens for setup. |
| Linux x86-64 | [Linux installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Linux-Setup.sh) | Save the file, then run `bash PortalAI-Academic-Linux-Setup.sh` in its download folder. |

Use the download links above, or the file page's **Download raw file** button. You do not need **Code > Download ZIP**. Linux browsers generally do not preserve the executable bit, so running the file with Bash avoids that extra step.

## Setup

Choose a new setup folder on the drive where PortalAI should live. Windows installs under that folder's `installer/PortalAI Windows`; Linux and Mac install in `PortalAI Academic Linux` or `PortalAI Academic Mac` beneath the chosen setup folder. Existing application folders are not overwritten.

The first stage downloads approximately 88 MB (Windows), 128 MB (Linux), or 102 MB (Mac). The full installers then fetch their pinned runtime/model dependencies; actual storage and download requirements are larger. Keep the setup folder on a drive with sufficient space. Verified downloads are reused if setup is run again.

Windows needs .NET Framework 4.5 or later, included in Windows 10/11. Linux and Mac need Bash, curl, tar, and a SHA-256 utility, usually supplied by the operating system. No host Python installation is needed. The Mac installer retains its existing Xcode/Metal toolchain and CMake requirements. These installers are unsigned; macOS or Windows may require the normal user approval to open a downloaded application. Do not disable OS security protections.

The original Academic restrictions and platform requirements are described in [the build documentation](Documentation/README.txt). These launchers preserve the original installer archives byte-for-byte. They only automate download, verification, reconstruction, extraction and installer startup.

## Repository contents

- The three setup downloads and their checksums are at the repository root.
- `packages/20261020-r1/` contains the verified package parts, grouped by operating system. The launchers download these automatically.
- `Documentation/` contains the Academic build details, source changes and validation records.
- `bootstrap-source/` contains the online launcher source and build instructions.

Maintainers can follow [the publishing guide](Documentation/PUBLISHING.md) to update this repository. Students only need the download for their operating system above.

## Build and verification

`PACKAGING.json` records the pinned part, reconstructed archive and extracted installer hashes. `SHA256SUMS` covers the published files. The launchers embed the expected hashes and do not trust a downloaded manifest to decide what code to run.

Maintainers can rebuild the launchers on Windows with Python 3.11+ and the .NET Framework C# compiler:

```text
python -B bootstrap-source/build.py
```

The native installer template is compatible with macOS Bash 3.2. `--prepare-only` plus a target directory allows download/extraction verification without starting an installation. See `bootstrap-source/VALIDATION.txt` for validation scope and commands.
