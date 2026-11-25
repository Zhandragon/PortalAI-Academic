# Current PortalAI Academic downloads

[Back to downloads](../README.md#download-and-install)

**Bundle 2026.11.25-bundle5** includes the native installers, complete optional model download catalogs, and compatible optional companions. Models download during installation; their weights are not embedded in these ZIPs.

| Choice | Application |
| --- | --- |
| [Windows](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle5/PortalAI-Academic-Windows-Bundle-2026.11.25-bundle5.zip) | r85, x64 |
| [Mac](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle5/PortalAI-Academic-Mac-Bundle-2026.11.25-bundle5.zip) | Experimental r75, Apple silicon / Intel |
| [Linux](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle5/PortalAI-Academic-Linux-Bundle-2026.11.25-bundle5.zip) | Experimental r75, x86-64 |
| [All three OSes](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle5/PortalAI-Academic-Universal-Bundle-2026.11.25-bundle5.zip) | Windows r85; Mac/Linux r75 |

## Install at the drive root or a folder you choose

1. Extract the entire ZIP into a new folder. Keep **Packages**, **Setup**, **Utilities** and the setup scripts together. The standalone launcher asset alone is not a complete installer bundle.
2. Windows: open **Start Setup.cmd**. Mac: open **Start Setup.command**. Linux: run **bash prepare-setup.sh**.
3. Choose the **installation root directory**. The default is the drive containing the bundle. Windows offers an editable field, **Browse** and **Drive root**; Mac/Linux ask in the terminal.
4. Choose the components, review model licenses, and install. Windows **All components** selects every available model and native companion; **Express** remains a small starter setup. Mac/Linux offer **Select all** in their model chooser and a separate optional suite chooser.

For a Windows root of `E:\`, the application goes in `E:\PortalAI Windows` and selected companions in `E:\Utilities`. Mac/Linux use **PortalAI Mac** and **PortalAI Linux** under their chosen root. **Platforms** contains prepared installer files only. Extracting the ZIP into a deeply nested folder does not change where the application is installed.

Existing application and selected companion folders are protected against accidental replacement. An unrelated **Utilities / Installers** folder is allowed. If setup has already prepared **Platforms**, run the native installer there directly; it also defaults to its drive root. Use **Update existing** or the native **--upgrade** workflow for an installed application.

Use NTFS on Windows, APFS on Mac, or executable ext4 on Linux. Each OS completes its own native installation; carrying all three installers on NTFS does not make Mac/Linux runtimes installed or supported on NTFS. [Requirements](INSTALLATION.md).

## Complete optional model downloads

Academic includes its complete eligible standard-model catalog, including ACE-Step 4B, Whisper Turbo and FLUX 9B FP8. Full-only assets and Portable Abliterator remain excluded. The complete Windows selection is about **274 GiB installed**, plus temporary installation space.

All model choices remain optional and retain their license and intended-use review. Selecting a model does not guarantee it fits the computer's RAM/VRAM or that every experimental Mac/Linux backend supports it. You can also supply your own compatible model.

FLUX downloads require the recipient's own publisher access and Hugging Face read token after accepting the publisher's terms. Tokens start empty, are used only during that installation, and are not stored in bundle files or receipts. GitHub credentials for private downloads are entered separately.

Setup verifies selected files and available space before installation. After a successful installation it removes verified completed temporary downloads; interrupted downloads remain available for retry. Enough space for the temporary downloads and final installation is required.

## Optional companions

Projection and **Home Assistant 0.5.13 + Recovery 0.1.0** are included in **Utilities / your OS**. Selecting Projection in the native suite chooser installs the clean bundled Projection and HA setup together in the root's **Utilities** folder. It does not pair a device or configure Home Assistant. Configure your own connection only when wanted; no credentials or user data are bundled.

Academic excludes Portable Abliterator and Full-only model assets.

Windows reset and Weight-Space Editor launchers remain in the native application where supported. Use them from the application's Utilities page. For an existing companion, preserve **Connections** and **state** and follow the [guarded upgrade guide](RELEASE-HA-0.5.13.md).

## Verification and current versions

The original Windows r85 and Mac/Linux r75 native archives remain byte-for-byte intact. Checksum-verified setup overlays add destination controls, complete model catalogs and current bundled companion selection. Prepared packages receive updated checksums. Mac/Linux companion installation restores verified executable permissions even if the ZIP was first extracted on Windows. The Windows extraction-path fix is retained: unused Mac test/debug files are omitted and paths reserve 120 characters for the extraction folder.

- [Whole-download checksums](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.11.25-bundle5/SHA256SUMS.txt)
- [Bundle manifest and build validation](DOWNLOAD-BUNDLES.json)
- [Windows r85](RELEASE-r85.md), [Mac/Linux r75](RELEASE-r75.md), [Home Assistant 0.5.13](RELEASE-HA-0.5.13.md)
- [Release history and tracked changes](RELEASE-HISTORY.md)

Each ZIP contains **bundle.json**, **BUNDLE-CONTENTS.json** and **SHA256SUMS**. PowerShell **-VerifyOnly** and Bash **--verify-only** verify preparation inputs without launching; **-ExtractOnly** / **--extract-only** prepares the native installer without launching.

A Linux regression test executes a copied launcher after its original executable bit has been lost; catalogs reject privileged permission bits. Validation covers archive contents, destination placement, optional model consent, credential handling, bundled companion placement, space checks and Windows UI behavior. Mac/Linux remain experimental. Fresh physical Mac/Linux installations and live inference were not rerun for this packaging update.
