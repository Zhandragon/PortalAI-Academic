PortalAI Universal — Academic — 2026.10.31-Desktop-r57

This fourth distribution prepares Windows, Linux and Mac packages together on
one drive. Run Prepare Universal.cmd on Windows, Prepare Universal.command on
Mac, or bash prepare-universal.sh on Linux. All three packages are size/SHA-256
verified before the current OS installer is offered. On Mac/Linux,
--prepare-only stops after downloads and --verify-only checks cached packages.
On Windows, use -PrepareOnly or -VerifyOnly with prepare-universal.ps1.
No host Python or Node is required. OS shell/network/archive utilities are used.

Each OS still completes its own native setup. This is not one executable or an
already installed three-OS application. The installers use separate application
folders and retain their platform/edition controls. They do not share accounts
or change existing private data. Windows offers Update existing; Unix supports
an existing destination with --upgrade. Follow each package's README.

Mac downloads portable pinned CMake and offers Apple-managed developer-tool
setup. Apple dialogs/licensing can require a later rerun. Internet, sufficient
RAM/storage and host OS/driver capabilities are still required. The Mac build
does not carry the full Windows media/VM stack. Neither physical Linux nor Mac
acceptance was performed on this Windows build host.

Use a destination the selected OS can write and execute. Stock macOS normally
cannot write NTFS. These tools do not format, repartition, add filesystem drivers
or silently switch installation to an internal disk. Choose an appropriate
writable destination before native setup. Windows/Linux x86-64 and Mac arm64/
x86-64 are the supported architecture targets; not arbitrary ARM PCs.

No files are deleted. A failed download removes only its own temporary download.
Old versions, accounts, credentials, settings, model choices and data are retained.

Academic packages download from the configured public GitHub release. Already populated Packages works
offline for preparation; native setup may still download dependencies.

Windows is r57; Linux and Mac remain r51. See universal.json for exact versions and hashes.
