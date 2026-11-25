# Publishing PortalAI Academic

The three setup downloads remain at the repository root. Current setup files use the immutable GitHub release URL and SHA-256 pins in PACKAGING.json. Format 3 uses one complete archive as its single download part. Prior Git-tracked parts remain available for old launchers; do not delete or convert them to LFS.

For a new release, build clean Academic-only installers, verify policy and payload hashes, upload the complete archives to a draft release, and update PACKAGING.json with the new tag, archive hashes and extracted-file hashes. Keep Windows installer files at ZIP root. Native archives use one top-level folder. Increment the bootstrap ownership markers so new versions cannot reuse an incompatible extraction folder.

Run `python -B bootstrap-source/build.py` on Windows with the .NET Framework compiler. Test exact launchers in prepare-only mode against verified assets, preserving Unix executable bits in the Mac app. Publish assets and commit the rebuilt launchers/source/docs as a coordinated release. Check server-side SHA-256 digests and public downloads. Never publish personal profiles, connections, tokens, cached browser state or Full-edition model assets. Full and Academic releases use separate repositories and separate manifests.

## Windows resources and universal setup

Build the maintained Windows launcher with `InstallerSources/Windows/build.py`, passing the verified matching `--runtime-zip`, an `--output` executable path and the existing `--icon`. The build requires Python, all four engine/update helpers, and `storage-plan.json` as embedded resources. Run the produced executable with `--verify-bootstrap`, inspect resource hashes, and exercise its storage-plan loader before packaging. Updating `.cs` or `.py` sources alone does not update an already compiled executable.

Recompute `PACKAGE_SHA256.json`, the complete archive hash, bootstrap metadata and universal manifest/TSV pins together. Universal sources live in `InstallerSources/Universal`; preserve executable ZIP modes for shell launchers. Test the edition-specific launcher path and missing/corrupt archives. Keep Full assets private and Academic assets separate. Preserve historical package parts and release archives needed by existing downloaders.

## Welcome-page download bundles

Current download bundles are built with tools/build_welcome_bundles.py and the
launchers in InstallerSources/Bundle. The native installer archives remain
unchanged. Optional Projection/HA files and, for Full Windows/Universal only,
Portable Abliterator setup are included beside them; main setup never runs them.

The build accepts --inputs, --output and --edition. Each input record supplies
key, path, sha256 and asset.browser_download_url. Required keys are the edition's
Windows/Mac/Linux installers, Projection/Windows, Projection/Mac,
Projection/Linux, HomeAssistant and HostUpdate. Full additionally requires
Abliterator/Windows. Academic builds require no Full/private inputs.
Use independently verified published hashes, not files from a personal install.

For subsequent releases, create new draft release IDs and a new bundle version.
Update tools/download-bundle-inputs.json with reviewed source pins and contents
manifests from the local builds. The manually dispatched Build current download
bundles workflow downloads those pinned inputs, reconstructs the bundles, checks
every member against the reviewed contents, and uploads to the task-owned draft.
It does not publish releases, change optional selections or change repository
visibility. Existing published assets are never overwritten. Update the current
download guide, four welcome-page buttons and DOWNLOAD-BUNDLES.json together only
after the draft assets pass verification. Retain the latest desktop release
pointer for existing updater clients. Archive superseded notices in release
history rather than appending them to the welcome page.

On Windows, run InstallerSources/Tests/test_download_bundles.py to exercise both
PowerShell and Git Bash preparation: correct entry points, optional components
left inactive, corrupt/missing packages, duplicate platforms, existing folders
and wrong-OS bundles. These checks do not replace native macOS/Linux acceptance.
