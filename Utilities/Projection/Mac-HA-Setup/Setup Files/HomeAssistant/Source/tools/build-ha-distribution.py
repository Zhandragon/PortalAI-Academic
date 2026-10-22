"""Build the allowlisted, credential-free HA distribution. Requires Node 20+."""
from pathlib import Path
import ast
import hashlib
import json
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.5.11"
NAME = "PortalAI-HomeAssistant-" + VERSION + "-recovery-0.1.0"
TEMPLATES = ['install.py', 'configure.py', 'finish.py', 'install.sh', 'Install Home Assistant.cmd', 'README_FIRST.txt', 'DISTRIBUTION.txt', 'VALIDATION.txt', 'RECOVERY.txt', 'STABILITY.txt', 'MERGE_NOTES.txt', 'AOOSTAR_HANDOFF.txt', 'HTTP_COMPATIBILITY.txt', 'PORTABLE_MERGE.txt', 'PORTABLE_VALIDATION.txt']
EXAMPLES = ['configuration.merge.yaml', 'resources.yaml', 'projection-dashboard.yaml', 'quick-chat-card.yaml', 'quick-controls-card.yaml', 'recovery-card.yaml', 'quick-view.yaml', 'desktop-projection-card.yaml']
COMPONENTS = {
    "portalai_native": ["__init__.py", "commands.py", "core.py", "schema.py", "workflows.py", "rich_protocol.py", "rich_chat.py", "manifest.json", "services.yaml"],
    "portalai_projection": ["__init__.py", "receiver.py", "viewer_demand.py", "manifest.json", "services.yaml"],
    "portalai_recovery": ["__init__.py", "receiver.py", "manifest.json", "services.yaml"],
}
WEB = ["visibility-grace.js", "catalog.js", "state.js", "portalai-viewer-demand.js", "live-state.js", "patch-dom.js", "rich-chat.js", "iphone-attachments.js", "native-workflows.js", "portalai-native-panel.js", "portalai-live-panel.js", "portalai-quick-card.js", "portalai-projection.js", "panel.css", "assets/icon.png", "assets/emblem.png", "assets/wordmark.png"]
TESTS = ["history-preview.test.mjs", "upload-v2.test.mjs", "visibility-grace.test.mjs", "test_upload_v2.py", "iphone-attachments.test.mjs", "live-state.test.mjs", "state.test.mjs", "test_native_receiver.py", "test_native_websocket.py", "test_quick_chat.py", "test_workflow_priority.py", "test_batch_media_receiver.py", "test_batch_rich_bridge.py", "test_ha_installer.py"]


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def build():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 20+ is required to rebuild the frontend bundles")
    for script in ("build-live.mjs", "build-quick.mjs", "build-projection.mjs"):
        subprocess.run([node, script], cwd=ROOT, check=True)
    files = {}

    def add(name, source):
        path = ROOT / source
        if path.is_symlink() or not path.is_file():
            raise ValueError("Expected a regular source file: " + str(path))
        data = path.read_bytes()
        if path.suffix == ".py":
            ast.parse(data.decode("utf-8-sig"), filename=source)
        files[name] = data

    for name in TEMPLATES + ["examples/" + name for name in EXAMPLES]:
        source = "distribution/HomeAssistant/" + name
        add(name, source)
        add("Source/" + source, source)
    for path in sorted((ROOT/'distribution/HomeAssistant/vendor').rglob('*')):
        if path.is_file() and path.suffix in ('.py','.txt'):
            source=path.relative_to(ROOT).as_posix()
            add(path.relative_to(ROOT/'distribution/HomeAssistant').as_posix(),source)
            add('Source/'+source,source)
    for domain, names in COMPONENTS.items():
        for name in names:
            relative = f"custom_components/{domain}/{name}"
            add(relative, "ha/" + relative)
            add("Source/ha/" + relative, "ha/" + relative)
        if json.loads(files[f"custom_components/{domain}/manifest.json"])["version"] != ('0.1.0' if domain=='portalai_recovery' else VERSION):
            raise ValueError("Integration version must match the release")
    for name in ("portalai-live-v0.5.11.js", "portalai-quick-chat-v0.4.3.js"):
        add("www/" + name, "dist/" + name)
    add("www/portalai-projection-v0.5.11.js", "dist/portalai-projection-v0.5.11.js")
    for name in WEB+['browser-crypto.js']:
        add("Source/web/" + name, "web/" + name)
    for name in TESTS+['browser-crypto.test.mjs','http-bundles.test.mjs','projection-lifecycle.test.mjs','test_ha_autosetup.py','test_recovery_receiver.py','iphone-review-server.mjs','iphone-review-fixture.js']:
        add("Source/tests/" + name, "tests/" + name)
    for name in ("build-live.mjs", "build-quick.mjs", "build-projection.mjs", "package.json", "tools/build-ha-distribution.py", "aoostar-compatibility-20261012/examples/ready-empty-unknown.json"):
        add("Source/" + name, name)
    files["RELEASE.json"] = (json.dumps({
        "name": "PortalAI Home Assistant", "version": VERSION, "release_date": "2026-10-16",
        "native_ui": "0.5.11", "quick_chat": "0.4.3", "desktop_card": "0.5.11 (reconnect fix retained)",
        "integrations": {name: '0.1.0' if name=='portalai_recovery' else VERSION for name in COMPONENTS},
        "distribution_revision": "portable-1", "host_changes_included": False, "cold_start_companion": False,
        "configuration_merge_required": False, "custom_yaml_layouts_may_require_manual_merge": True, "python_installer_minimum": "3.9",
        "edition":"0.5.11-recovery-0.1.0", "first_pairing_required":True, "recovery_helper_required":True,
    }, indent=2) + "\n").encode()
    # Avoid accidentally redistributing this workstation's identities or URLs.
    # Keep the exact private values out of the builder shipped in the archive.
    for name, data in files.items():
        if name.endswith((".png",)):
            continue
        if b".ui.nabu.casa" in data or b"C:\\Users\\" in data or b"C:/Users/" in data:
            if name != "Source/tools/build-ha-distribution.py":
                raise ValueError("Private deployment reference in: " + name)
    files["SHA256SUMS.json"] = (json.dumps({name: checksum(data) for name, data in sorted(files.items())}, indent=2) + "\n").encode()
    output = ROOT / "dist" / NAME / "HomeAssistant"
    output.mkdir(parents=True, exist_ok=True)
    # Never recursively delete an existing staging directory. Refuse unexpected
    # files so a release cannot accidentally absorb hand-edited/private extras.
    for path in output.rglob("*"):
        if path.is_symlink() or (path.is_file() and path.relative_to(output).as_posix() not in files):
            raise ValueError("Unexpected staging file; use a clean output directory: " + str(path))
    for name, data in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    archive = ROOT / "dist" / (NAME + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo("HomeAssistant/" + name, date_time=(2026, 10, 16, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            target.writestr(info, data)
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None or len(check.namelist()) != len(files):
            raise ValueError("ZIP verification failed")
        for name, data in files.items():
            if check.read("HomeAssistant/" + name) != data:
                raise ValueError("ZIP payload mismatch: " + name)
    sha = checksum(archive.read_bytes())
    archive.with_suffix(".sha256").write_text(sha + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size, "sha256": sha}, indent=2))


if __name__ == "__main__":
    build()
