# Installer disk-space checks — 2026-10-22 r3

## Disk-space checks before installation

The current installers check the **actual destination volume** before downloading dependencies or extracting the application. The message shows required space, available space and any shortfall. An unreadable or disconnected destination stops setup. This is a disk-capacity check; RAM and VRAM requirements are separate.

Windows calculates the selected components and their dependencies from the release manifest, including expanded files, unique retained downloads, filesystem allocation overhead and 1 GiB of working space. Its first check also includes unpacking the small setup runtime. It checks again after downloading, before application extraction. The budget is conservative: existing cached downloads are not subtracted from the initial free-space requirement.

Linux and macOS check their initial native installation, bundled runtime expansion, initial models and working space before extraction. Their budgets include conservative dependency allowances (8 GiB Linux; 4 GiB macOS), 8 GiB for the Mac backend build, allocation slack for filesystems with allocation units up to 64 KiB, and 1 GiB of scratch space. They preserve the existing 100 GiB output reserve plus the larger of 50 GiB or 10% of the destination filesystem's capacity as free-space reserve. Optional later model/media installs retain their own checks. Native package resolution and compiler output vary by host, so these are conservative budgets rather than byte-exact predictions.

Academic's small download launchers also check the setup location before downloading the complete installer. Windows checks the required baseline at this stage and checks the final component selection in the next window. Native launchers include both setup files and the initial native installation. The explicit `--prepare-only` mode checks only download/extraction space because it does not install the application.

The Windows packages now include the checksum-pinned SoX archive, avoiding a separate SourceForge mirror request during audio-tool setup. Other download failures identify the artifact and URL. HTTPS certificate verification and file-size/SHA-256 checks remain enabled.

If space is insufficient, choose a larger drive, free space, or reduce optional Windows components before retrying. Other programs can consume disk space after a check, so later storage checks remain active. These checks do not establish fresh physical Linux/macOS installation validation.

## Validation

- 18 storage and download regression tests pass for each edition, covering allocation overhead, shared downloads, nested paths, unavailable/insufficient space, exact boundaries, stopping before downloads/extraction, a second extraction check, certificate diagnostics and bundled-file verification.
- Both compiled Windows installers were exercised on an insufficient-space destination; neither unpacked its setup runtime. Exact/low-space comparison boundaries passed.
- Native shell and Academic bootstrap checks were exercised with simulated low/unreadable destination space. Native archive modes and links, archive/member hashes, and unchanged third-party dependency pins were checked.
- SoX was downloaded over verified HTTPS and matched the existing 2,651,143-byte SHA-256 pin. The Windows installer uses this verified bundled archive; corrupt or missing bundled files stop installation.
- These are targeted installer/packaging checks on Windows. Physical Linux/macOS installation and model inference were not rerun.

Run the portable Python regression suite with `python InstallerSources/Tests/test_storage_preflight.py`. Bash is needed for the four native shell cases. See [current downloads](../README.md#download-and-install).
