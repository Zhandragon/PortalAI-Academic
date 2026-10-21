# Publishing PortalAI Academic

The distribution is hosted at `Zhandragon/PortalAI-Academic`, branch `main`. Keep the three setup downloads at the repository root. The launchers contain fixed URLs under `packages/20261021-r1/` and pinned hashes for every part, reconstructed archive and extracted installer file.

## Repository layout

```text
PortalAI-Academic-Windows-Setup.exe
PortalAI-Academic-Mac-Setup.zip
PortalAI-Academic-Linux-Setup.sh
packages/20261021-r1/{Windows,Linux,Mac}/
Documentation/
bootstrap-source/
PACKAGING.json
SHA256SUMS
LICENSE
README.md
```

There are four Windows parts, six Linux parts and five Mac parts. All 15 parts are required. Each is at most 24,000,000 bytes. The launchers reconstruct the original Academic installer archives byte-for-byte, then start those installers. Runtime and model dependencies are downloaded by the full installers as described in the build documentation.

## Updating the distribution

1. Pull the latest `main` branch into a local clone before editing.
2. Build and verify the complete distribution. Preserve the package directory structure and keep its paths consistent with the embedded launcher URLs.
3. Commit the launchers, every required package part, source, metadata, checksums and documentation together. Preserve the existing license. Use a normal Git push; the complete upload failed through the browser uploader on this host.
4. Confirm that all three public download links in the repository README work. Download the package parts through their public URLs, verify every SHA-256 hash and verify the reconstructed archive hashes before distributing the links.

For a future installer revision, publish its parts under a new versioned directory and rebuild the launchers with the new paths and hashes. Keep existing versioned parts available for students who downloaded an older launcher.

Do not commit the full original archives, reconstructed files, download caches or an extra enclosing `GitHub-One-Click` directory. Do not convert package parts to Git LFS: the launchers expect binary file contents from GitHub's raw endpoint. No separate release assets are needed for this distribution.

`PACKAGING.json` describes the full installer archives, parts and extracted files. `SHA256SUMS` covers the distribution files other than itself; the existing repository license is preserved separately. The launcher source and prepublication validation details are under `bootstrap-source/`.

## Validation scope

See [the Academic build documentation](README.txt) and [launcher validation](../bootstrap-source/VALIDATION.txt). Download and checksum verification does not establish that a full application installation or model workflow has run successfully on every supported operating system.
