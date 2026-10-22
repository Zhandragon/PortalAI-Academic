PORTALAI CLEAN LINUX INSTALLER
Release: PortalAI-2026.10.19-Linux-x86_64-r13
Documentation revision: 1 (2026-10-19)
Target: Linux x86-64, glibc 2.28 or newer

INSTALL

1. Put this installer archive on the drive where you want PortalAI to live,
   then extract it into a new folder on that drive.
2. Open a terminal in that folder and run:

   ./install.sh

   The default destination is a `PortalAI Linux` folder inside this extracted
   installer folder, beside install.sh, regardless of the launch directory. The app stays
   on the same drive when you move it.
   Or choose a different destination:

   ./install.sh "$HOME/Applications/PortalAI Linux"

   Or install to a different drive location using an explicit path:

   ./install.sh "/path/to/installer-folder/PortalAI Linux"

3. After installation, start PortalAI with:

   "./PortalAI Linux/PortalAI.sh"

The installer requires a POSIX shell, coreutils (including sha256sum), tar, and
an internet connection. It needs no sudo, host Python, host Node.js, system-wide
package installation, or Home Assistant login. It checks checksums, installs
into a staging directory on the chosen volume, verifies that it supports Unix
executable bits, refuses to replace an existing destination, and moves the
completed app into place only after the core checks pass. Choose a filesystem
mounted read/write by Linux that preserves executable permissions; Windows
NTFS volumes may need Linux mount configuration for this.

WHAT IT INSTALLS

- Clean PortalAI application source from the Windows clean release identified
  by source_release in manifest.json, filtered of Windows executables and owner
  data. This package includes the desktop r23 UI responsiveness merge and earlier task checkpoint fixes.
- The pinned standalone CPython 3.12.15 Linux x86-64 runtime.
- The Linux CPU llama.cpp backend and verified Linux QEMU runtime.
- A private Debian Trixie rootfs, Linux GUI Python packages, and Linux account
  dependencies. These are fetched from Debian and PyPI over HTTPS, hash checked,
  and stored under the PortalAI folder. The installer does not run package
  maintainer scripts or install anything into the host OS.

Models, user accounts, wallet credentials, Google credentials, mission history,
outputs, and Home Assistant pairing data are not included. Add a supported GGUF
model before expecting local LLM chat. The installer does not arm or schedule a
mission at first launch.

The private Debian rootfs expands to about 1 GiB; network download size varies
with the selected Debian package versions, plus the pinned Python wheels. The
installer preserves the
storage reserve configured in Agent/hardware_profiles.json; the current policy
also requires roughly 3 GiB of working space for the system layer. An app volume
must have enough free space to satisfy both requirements.

PLATFORM LIMITS

This installer targets Linux x86-64 only. Persistent jobs require a supported
cgroup v2/systemd user scope. Optional CPU Torch, science, media, CUDA, and ROCm
layers are not installed by the core profile; GPU/physical Linux combinations
remain hardware dependent. Use the app's Diagnostics and the Linux packaging
notes to check optional components. Linux model weights are not included.

This is not a macOS installer. Use the separate universal Mac installer for
Apple silicon or Intel Macs. Each OS installer creates its own named app folder
inside its installer folder, so installations can share a parent without
mixing platform runtimes.

INTEGRITY AND PRIVACY

SHA256SUMS checks the two bundled payload archives before extraction. The
embedded Python, Debian packages, PyPI wheels, and installed Linux layers are
checked again against their recorded hashes. The package contains no signed-in
owner account or credentials. The Linux CPU and QEMU third-party license notices
are included beside their binaries.

Build provenance and scope are recorded in manifest.json and in the installed
Maintenance/Imports/linux-clean-installer-r13.json. The archive passes build-time
integrity and static package checks. The full Linux guest test and an online
recipient install could not be run on the Windows build host because WSL is not
installed and free RAM is below the test's 14-GiB minimum. Physical Linux
desktop, driver, audio device, GPU, and KVM behavior remains unverified.

2026-10-19 r13: shared GUI style reuse avoids global theme redraws on menu opening.
See Documentation/UI_Responsiveness_20261019.txt in the application.
