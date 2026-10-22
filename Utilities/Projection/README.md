# PortalAI Projection

Optional companion for the existing PortalAI application. **macOS Projection is now packaged for Intel and Apple silicon (macOS 14+); native Mac acceptance remains pending.** Windows x64 and Linux x86-64 packages are provided; Linux requires X11/XWayland and delegated cgroup v2 memory control. See the [full setup guide](../../Documentation/PROJECTION.md) for requirements and validation limits.

| Host | One-file download | Reconstructed download size |
| --- | --- | --- |
| Windows x64 | [Projection setup](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-Projection-Windows-Setup.exe) | About 22 MB |
| Linux x86-64 | [Projection setup](https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection/PortalAI-Projection-Linux-Setup.sh) | About 61 MB |

Open the Windows file or run `bash PortalAI-Projection-Linux-Setup.sh`. Choose a **new directory on the same drive as PortalAI**. Setup downloads and verifies the platform's parts, reconstructs its archive, verifies all extracted files and opens Projection. Keep roughly 0.5 GB free for the download cache, archive and extracted companion. After setup, use `utilities/PortalAI-Projection/Start Projection.cmd` or `Start Projection.sh` directly.

The extracted `utilities` directory contains `PortalAI-Projection` and the sibling `PortalAI HA Setup`. Bundled Python/Tk/TLS runtimes avoid a host Python or Node requirement. The matching [Home Assistant 0.5.11 + Recovery 0.1.0 ZIP](PortalAI-HomeAssistant-0.5.11-recovery-0.1.0.zip) is also available separately for installation on a trusted HA device. This installs PortalAI integrations into an existing HA server; it does not install Home Assistant OS.

No saved connections, private device keys, pairing identities, account data, logs or captures are included. Choose your own Academic application folder, create a new connection and approve its public pairing request on your own HA instance. Optional recovery is available on Windows and Mac and must be separately armed/paired.

## Maintainer files

`PACKAGING.json` pins every part, reconstructed archive and extracted file. Individual downloads have adjacent `.sha256` files; the repository-wide `SHA256SUMS` also covers this directory. Each part is at most 24,000,000 bytes. Production downloaders use HTTPS and embed their expected hashes instead of trusting a downloaded manifest.

`source/app/` contains the companion's Python source. `source/Bootstrapper.cs.in`, `source/native.sh.in` and `source/build.py` implement the separate utility downloaders. Their ownership markers and extraction directory differ from the main Academic installers. The only companion launcher adjustment creates empty Windows connection/state directories on a fresh installation. The Windows/Linux companion archives remain unchanged; see the current release for updated application installers and the Mac companion.

To rebuild these downloaders on Windows with Python 3.11+ and the .NET Framework C# compiler:

```text
python -B Utilities/Projection/source/build.py
```

To create a **new** distribution from an owned companion and its matching HA setup, update the version in `source/package.py` and both downloader templates, then use a fresh staging directory:

```text
python -B Utilities/Projection/source/package.py --projection-source "PATH/PortalAI-Projection" --ha-setup-source "PATH/PortalAI HA Setup" --work "NEW-STAGING-DIRECTORY"
python -B Utilities/Projection/source/build.py
```

The packager copies allowlisted runtime receipt entries and explicitly selected app/launcher dependencies, verifies the HA manifest, and excludes private state. It refuses an existing staging directory or versioned part directory. `source/PROVENANCE.json` records source receipt hashes and the two changed upstream package `RECORD` metadata files; published hashes describe the actual distributed bytes. Preserve runtime licenses when updating dependencies.

For isolated downloader checks, build into another directory with `--output` and a local test `--source-base-url`. Windows accepts `--prepare-only PATH`; Linux accepts `--directory PATH --prepare-only`. These flags verify extraction without opening Projection. See [validation results](source/VALIDATION.json). Linux reconstruction was checked under Git Bash; it does not establish physical Linux desktop or HA Cloud compatibility.

## Mac companion (20261021-r1)

[Download Mac Projection + HA setup](https://github.com/Zhandragon/PortalAI-Academic/releases/download/v2026.10.21-r2/PortalAI-Mac-Projection-HA-20261021-r1.tar.gz). This standalone bundle is edition-neutral, supports Intel and Apple silicon on macOS 14+, and is included in both current Mac installers. Open `Utilities/PortalAI-Projection/Start Projection.command`. Native Mac acceptance is pending. [Setup instructions](../../Documentation/MacProjection/SETUP.txt). [Current validation](../../Documentation/MacProjection/validation.json). The Windows/Linux downloader hashes above still describe their previous bundles.
