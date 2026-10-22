# PortalAI portable bundle

On Windows, open **PortalAI.exe** at the SSD root, or **Start PortalAI Windows.cmd**. The rebuilt drive-level launcher recognizes **PortalAI Windows**, **PortalAI**, and **PortableAI**; exactly one of these application folders must be beside it. Opening PortalAI.exe inside the application folder also works.

The October 18 account repair restores setup/login before the main interface. This reviewed registry-free copy offers initial administrator creation and preserves its existing chat/settings through verified encrypted migration and an external encrypted recovery backup. Choose your own administrator name and password (at least 12 characters). Existing or damaged account registries still require authenticated recovery. See Documentation/Accounts_Launcher_Repair_20261018.txt.

Windows, Linux and Mac each use their own clean installer and native runtime. Extract the complete installer into the folder where PortalAI should live, on any drive. Windows Install here creates PortalAI Windows, Utilities and PortalAI.exe beside PortalAI-Install.exe. Linux creates PortalAI Linux beside install.sh; Mac creates PortalAI Mac beside install-macos.sh. No drive letter is fixed. Existing application folders are never overwritten. Start Windows with PortalAI.exe, Linux with PortalAI.sh inside its app folder, and Mac with PortalAI.app. macOS generally cannot write NTFS volumes by default; use a writable filesystem supporting native execution. Do not launch the same profile from multiple operating systems at once.

- **Accounts**: the Current Account card, Change current user, Export Data (chat history, outputs or both), passwords and administrator account management. Switching verifies the new credentials before sealing the current account. Start fresh requires a separate final confirmation.
- **Controls**: the six lifecycle/test buttons, followed by **Control Log**.
- **Chat**: conversation, history, tools and personal **Chat Preferences**.
- **Runtime**: CPU/RAM/GPU/VRAM charts, concurrent owned tools and reported models. Unavailable driver counters are labelled honestly.
- **Models**: loaded components and service/mission state.
- **Packages**: searchable, paged installed capabilities with two columns on wide windows, plus a separate Weights & LoRAs subtab.
- **Settings**: shared model/backend/context policy and media defaults, each with independent Save and Check hardware fit actions. Use Stop all components → Startup to change a loaded chat model.
- **Persistence**: directly accessible Missions & access and Schedules pages; administration is required.
- **Maintenance**: diagnostics, storage checks, reviewed cleanup and independently saved **Storage reserves**. Reports include Copy to clipboard; copying includes the full report even when its preview is truncated.
- **Help**: searchable documentation and contextual guidance.

Open **Art Assets/Gallery.html** to browse 50 verified copies of the public logos, icons, wordmarks and other artwork. The application originals remain in their existing locations.

Windows, Linux and macOS have separate bundled runtimes and installers. Windows NVIDIA and bounded offline Linux guest checks are documented; physical Radeon/laptop/Linux desktop, audio-device and KVM combinations remain unvalidated. The Mac package builds its Metal backend on the recipient Mac and has not had full physical recipient validation. Vulkan chat does not enable CUDA-only media on Radeon. See the platform installer notes for current limits.

Storage reserves protect output room plus a free-space floor; they are managed-write checks, not OS quotas. Missions retain per-mission Full/Observe/offline-VM boundaries. Account workspaces are application privacy, not OS isolation. Exit normally and wait for verified account sealing before removing or moving the drive.

The October 11 visual/rename follow-up is documented in Documentation/Rounded_Navigation_20261011.txt. Existing compatibility filenames, numbered master instructions, historical reports and encrypted generations are preserved. Source recovery snapshots under Maintenance/Patches and their C-drive mirrors are not complete SSD backups.

The current Windows folder is PortalAI Windows. The earlier account-switching and visual-hierarchy changes are documented in Documentation/Accounts_UX_20261011.txt.

The compact layouts and Persistence navigation are documented in Documentation/Compact_Panels_20261011.txt.

PortalAI Academic: This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students. See Documentation/PortalAI_Academic.txt.
