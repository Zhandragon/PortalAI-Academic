# Installing PortalAI (Academic)

[Documentation index](README.md) · [Current installer downloads](../README.md#download-and-install)

## Drive format and preparation

Use **NTFS for Windows, APFS for macOS, and ext4 for Linux** for the volume containing PortalAI. These recommendations apply to the setup/extraction folder, the installed application and its native runtimes, whether the drive is internal or external. Check the drive's existing format first; a correctly formatted, writable volume does not need reformatting. **Formatting erases existing data, so make a verified backup before changing a drive's format.**

| Platform | Recommended format | Why it fits PortalAI |
| --- | --- | --- |
| Windows | **NTFS** | Supports large model files, Windows access-control lists, links and metadata journaling. PortalAI's Windows runtime preparation includes native permission checks. |
| macOS | **APFS**, using the standard case-insensitive format | Apple's native format for modern Macs, optimized for SSDs and suitable for external drives. It preserves the native file metadata and links needed by bundled runtimes and local builds. Select **GUID Partition Map** when initializing a new drive in Disk Utility. |
| Linux | **ext4** | A mature, widely supported Linux filesystem with large-file support, Unix ownership and executable permissions, symbolic links and journaling. It is the straightforward default for a dedicated portable PortalAI drive. |

On Linux, the volume must be mounted **read/write with execution permitted**; a `noexec` mount prevents bundled programs from running even if a launcher is invoked with Bash. The installing user must own or have write access to the chosen application directory. Keep normal executable permissions and symbolic links when extracting native packages, and run the installer as your regular user. Existing native filesystems such as XFS or Btrfs can provide the required features, but ext4 is our recommendation for a newly prepared PortalAI drive; this is not a separate validation claim for those alternatives.

On a Mac, choose standard **APFS**, rather than a case-sensitive variant, as the default for a new application drive. macOS normally cannot write to NTFS without an additional driver, so a Windows NTFS installation drive is not the recommended Mac destination. An APFS volume must be mounted and writable before installation or launch.

**FAT32 and exFAT are not recommended installation formats.** FAT32's maximum individual file size is less than 4 GiB, below many PortalAI model files. exFAT supports large files but does not preserve native Unix permissions or symbolic links and lacks Windows access-control lists and filesystem journaling. Being able to copy a model onto a drive does not establish that the complete application can install and run there.

For use across operating systems, keep separate OS-specific installations on appropriately formatted volumes or drives. A separate exFAT volume is useful for transferring intact installer archives or exported documents/media; extract native application files on their destination filesystem. Do not run one account/profile concurrently from multiple operating systems. Exit PortalAI normally, wait for saving and account sealing to finish, and safely eject before unplugging.

These filesystem recommendations follow the installers' native runtime requirements; they do not change the platform-testing limits below or claim new physical Mac/Linux validation. See [Microsoft's filesystem comparison](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison), [Apple's APFS guidance](https://support.apple.com/guide/disk-utility/file-system-formats-dsku19ed921c/mac), [Apple's partition schemes](https://support.apple.com/guide/disk-utility/partition-schemes-dsku1c614201/mac), and the Linux kernel documentation for [ext4 file metadata and permissions](https://docs.kernel.org/filesystems/ext4/inodes.html) and [journaling](https://docs.kernel.org/filesystems/ext4/journal.html).

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

[Chat timeline update and current installers](CHAT-TIMELINE-20261022.md).

**Latest update: mission review instructions.** Add corrections or responses to a paused mission or scheduled run, retain review history, and re-enable reviewed schedules. [Details and current installers](MISSION-REVIEW-20261022.md).

