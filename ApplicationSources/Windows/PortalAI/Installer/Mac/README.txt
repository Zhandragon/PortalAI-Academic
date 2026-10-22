PortalAI Mac Clean Installer r13

Put PortalAI-Mac-Clean-Installer-20261019-r13-universal.tar.gz on the drive
where you want PortalAI to live, extract it into a new folder there, then run:

  cd PortalAI-Mac-Clean-Installer-r13
  bash install-macos.sh

This package supports Apple silicon arm64 and Intel x86_64. It requires Xcode's
Metal compiler, CMake, and the storage/output reserves described in the bundled
Documentation/Mac_Clean_Installer_20261017.txt. It is unsigned/not notarized
and does not include model weights or personal account data.

The default install folder is `PortalAI Mac` inside the extracted release
folder, alongside install-macos.sh. You may pass a different destination as the
first argument. The selected volume must be writable by macOS and provide
the space required for the local Metal build. The current Windows SSDs are NTFS;
macOS may read NTFS volumes but does not write to them by default, so this Mac
installer stops before extracting the app if its destination is not writable.
Run PortalAI.app on the Mac; a Windows or Linux launcher cannot start the Mac
application.

2026-10-19 r13: shared GUI style reuse avoids global theme redraws on menu opening.
See Documentation/UI_Responsiveness_20261019.txt in the application.

October 18 r4: includes account startup, chat context/checkpoint, read-only chat_history, and account-aware media input fixes. Runtime pins are unchanged. Full physical recipient installation remains untested.

The default install location follows the installer script, regardless of the drive or download folder. An explicit first path argument may override it. Existing application folders are refused.

October 18 r5 adds rolling checkpoints during long tool tasks, automatic follow-up working state and an explicit tool-call budget (0 = unlimited). No runtime pins or installation placement rules changed.

October 18 r6 adds explicit dialogue video timing, bounded motion/lip-sync segments and exact paged evidence under compaction. No runtime pins or installation placement rules changed.

October 18 r7 adds compact discovery guidance, complete basic tool help under compaction and repeated-discovery recovery. No runtime pins or installation placement rules changed.

October 18 r8 adds precise ComfyUI failure classification and bounded traceback evidence without automatic replay. No runtime pins or installation placement rules changed.

October 18 r9 adds Windows commit-aware CUDA model loading. Radeon/Linux/Mac loading policies and runtime pins remain unchanged.

October 18 r10 adds bounded recovery when a reasoning checkpoint summary is incomplete. Original history, results, Stop, login and no-replay guards remain.

Proactive task checkpoints: Nice receives cycle-budget estimates and can save progress then continue automatically within the active request. Incomplete emergency summaries recover from saved notes. Stop, login and no-replay guards remain.
