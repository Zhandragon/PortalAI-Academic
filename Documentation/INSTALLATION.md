# Installing PortalAI (Academic)

[Documentation index](README.md) · [Current installer downloads](../README.md#download-and-install)

## Download and launch

Download **one file for your operating system**. The launcher downloads its pinned complete installer from this repository’s GitHub release, verifies the archive and extracted files, and starts the Academic installation. Older downloaded launchers can still use their original retained package parts.

| Operating system | Download | Open it |
| --- | --- | --- |
| Windows x64 | [Windows installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Windows-Setup.exe) | Open the `.exe`, choose the setup location, and click **Download and install**. Continue in the full installer window. |
| Linux x86-64 | [Linux installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Linux-Setup.sh) | Save the file, then run `bash PortalAI-Academic-Linux-Setup.sh` in its download folder. |
| macOS, Apple silicon / Intel | [Mac installer](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/PortalAI-Academic-Mac-Setup.zip) | Extract the ZIP and open **PortalAI Academic Installer.app**. Terminal opens for setup. |

Use the download links above, or the file page's **Download raw file** button. You do not need **Code > Download ZIP**. Linux browsers generally do not preserve the executable bit, so running the file with Bash avoids that extra step.

## Destination, space and prerequisites

Choose a new setup folder on the drive where PortalAI should live. Windows installs under that folder's `installer/PortalAI Windows`; Linux and Mac install in `PortalAI Academic Linux` or `PortalAI Academic Mac` beneath the chosen setup folder. Existing application folders are not overwritten.

The first stage downloads approximately 344 MB (Windows), 557 MB (Linux), or 680 MB (Mac). The full installers then fetch their pinned runtime/model dependencies; actual storage and download requirements are larger. Keep the setup folder on a drive with sufficient space. Verified downloads are reused if setup is run again.

Windows needs .NET Framework 4.5 or later, included in Windows 10/11. Linux and Mac need Bash, curl, tar, and a SHA-256 utility, usually supplied by the operating system. No host Python installation is needed. The Mac installer retains its existing Xcode/Metal toolchain and CMake requirements. These installers are unsigned; macOS or Windows may require the normal user approval to open a downloaded application. Do not disable OS security protections.

The original Academic restrictions and platform requirements are described in [the build documentation](README.txt). These launchers reconstruct their pinned release archives byte-for-byte. They only automate download, verification, reconstruction, extraction and installer startup.

## Edition behavior

The installer fetches the standard Qwen 1.7B chat model. Windows offers larger standard chat/vision and media components; native installers retain their platform-specific scope. Academic enforces standard/censored chat, vision and media. Abliterated/uncensored models, anatomical LoRAs and Portable Abliterator are excluded. Visible variant controls are inert, and their context help explains the edition.

The current r2 installers label intentionally omitted assets EXCLUDED. Missing required standard dependencies, unsupported platforms and insufficient memory can still prevent a workflow from running. See the [release notes](../README.md#release-notes) and [validation record](VALIDATION.json).

## Accounts and support

Create your own account after installation. Help and searchable documentation are available in PortalAI itself. Only Windows has been thoroughly tested; Linux has partial validation and physical macOS installation remains unvalidated. Report errors to the [maintainer](https://github.com/Zhandragon/PortalAI-Academic/issues), including OS and installer versions and error text without passwords, tokens or private content. **macOS Projection is now packaged for Intel and Apple silicon (macOS 14+); native Mac acceptance remains pending.**

The current installers include web tools, collaborating agents and configurable ports. See [the silent web update](SILENT-WEB-20261021.md) for current package versions, instructions and validation limits.
