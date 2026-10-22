"""Filesystem installer tests in isolated temporary directories; no live HA."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ha_installer", ROOT / "distribution/HomeAssistant/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "HA config"
        self.root.mkdir()
        (self.root / "configuration.yaml").write_bytes(b"existing: config\r\n")
        (self.root / ".storage").mkdir()
        (self.root / ".storage/pairing").write_text("private fixture", encoding="utf-8")
        self.package = Path(self.temp.name) / "package"
        self.package.mkdir()
        self.data = {
            "custom_components/portalai_native/__init__.py": b"# new native\n",
            "custom_components/portalai_projection/__init__.py": b"# new projection\n",
            "custom_components/portalai_recovery/__init__.py": b"# recovery\n",
            "www/portalai-live-v0.5.12.js": b"// new native UI\n",
            "www/portalai-quick-chat-v0.4.3.js": b"// quick\n",
            "www/portalai-projection-v0.5.12.js": b"// desktop\n",
            "examples/configuration.merge.yaml": b"device_id: REPLACE_WITH_MODULE_DEVICE_ID\n",
            "RELEASE.json": b'{"version":"0.5.12"}',
            "install.py": (ROOT / "distribution/HomeAssistant/install.py").read_bytes(),
        }
        for domain in ("portalai_native", "portalai_projection", "portalai_recovery"):
            self.data[f"custom_components/{domain}/manifest.json"] = b'{"version":"0.5.12"}'
            self.data[f"custom_components/{domain}/services.yaml"] = b"services: {}\n"
        for name in ('configure.py','finish.py','vendor/PyYAML-LICENSE.txt','vendor/yaml/__init__.py'):
            self.data[name]=(ROOT/'distribution/HomeAssistant'/name).read_bytes()
        for name, data in self.data.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.manifest()
        self.files = installer.payload(self.package, "a" * 32)

    def manifest(self):
        (self.package / "SHA256SUMS.json").write_text(json.dumps({name: installer.digest(data) for name, data in self.data.items()}), encoding="utf-8")

    def install(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return installer.install(self.root, self.files)

    def assert_private_preserved(self):
        self.assertEqual((self.root / "configuration.yaml").read_bytes(), b"existing: config\r\n")
        self.assertEqual((self.root / ".storage/pairing").read_bytes(), b"private fixture")

    def test_fresh_install_personalized_examples_and_idempotence(self):
        backup = self.install()
        self.assertIsNotNone(backup)
        self.assert_private_preserved()
        for name, data in self.files.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        self.assertIn(b"a" * 32, (self.root / "portalai/examples/0.5.12/configuration.merge.yaml").read_bytes())
        self.assertIsNone(self.install())
        self.assertEqual(len(list((self.root / ".portalai-installer/backups").iterdir())), 1)

    def test_upgrade_and_rollback_restore_exact_previous_bytes(self):
        old = self.root / "custom_components/portalai_native/__init__.py"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"# previous user version\n")
        legacy = self.root / "www/portalai-live-v0.5.1.js"
        legacy.parent.mkdir()
        legacy.write_bytes(b"old versioned frontend")
        backup = self.install()
        installer.rollback(self.root, backup)
        self.assertEqual(old.read_bytes(), b"# previous user version\n")
        self.assertEqual(legacy.read_bytes(), b"old versioned frontend")
        self.assertFalse((self.root / "www/portalai-live-v0.5.12.js").exists())
        self.assert_private_preserved()
        installer.rollback(self.root, backup)  # Repeated rollback is harmless.

    def test_plan_writes_nothing_and_cli_round_trip(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        def cli(*args):
            return subprocess.run([sys.executable, "-B", str(self.package / "install.py"), *args], capture_output=True, text=True)
        result = cli("plan", "--files-only", "--config", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")))
        self.assertEqual(cli("install", "--files-only", "--config", str(self.root)).returncode, 0)
        backup = next((self.root / ".portalai-installer/backups").iterdir()).relative_to(self.root).as_posix()
        self.assertEqual(cli("rollback", "--config", str(self.root), "--backup", backup).returncode, 0)
        self.assert_private_preserved()

    def test_tampered_or_unlisted_payload_refused_before_install(self):
        (self.package / "www/portalai-live-v0.5.12.js").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum failed"):
            installer.payload(self.package, "a" * 32)
        (self.package / "www/portalai-live-v0.5.12.js").write_bytes(self.data["www/portalai-live-v0.5.12.js"])
        (self.package / "custom_components/portalai_native/extra.py").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "Unlisted"):
            installer.payload(self.package, "a" * 32)
        self.assertFalse((self.root / ".portalai-installer").exists())

    def test_partial_write_failure_restores_previous_install(self):
        old = self.root / "custom_components/portalai_native/__init__.py"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"# original\n")
        write = installer.atomic_write
        failed = False
        def injected(root, name, data):
            nonlocal failed
            if root == self.root and name.startswith("www/") and not failed:
                failed = True
                raise OSError("simulated disk failure")
            return write(root, name, data)
        with patch.object(installer, "atomic_write", side_effect=injected):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                self.install()
        self.assertEqual(old.read_bytes(), b"# original\n")
        self.assertFalse((self.root / "custom_components/portalai_projection/__init__.py").exists())
        self.assertFalse((self.root / ".portalai-installer/install.lock").exists())
        self.assert_private_preserved()

    def test_rollback_refuses_later_user_edit_before_any_restoration(self):
        backup = self.install()
        new = self.root / "www/portalai-live-v0.5.12.js"
        new.write_bytes(b"user edit after install")
        with self.assertRaisesRegex(ValueError, "Changed since installation"):
            installer.rollback(self.root, backup)
        self.assertEqual(new.read_bytes(), b"user edit after install")
        self.assertEqual((self.root / "custom_components/portalai_native/__init__.py").read_bytes(), self.files["custom_components/portalai_native/__init__.py"])

    def test_corrupt_backup_refused(self):
        old = self.root / "custom_components/portalai_native/__init__.py"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"original")
        backup = self.install()
        (self.root / backup / "files/custom_components/portalai_native/__init__.py").write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "Backup checksum failed"):
            installer.rollback(self.root, backup)
        self.assertEqual(old.read_bytes(), self.files["custom_components/portalai_native/__init__.py"])

    def test_interrupted_prepared_journal_with_partial_payload_restores(self):
        old = self.root / "custom_components/portalai_native/__init__.py"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"original")
        backup = self.install()
        journal_path = self.root / backup / "journal.json"
        journal = json.loads(journal_path.read_text())
        journal["state"] = "prepared"
        journal_path.write_text(json.dumps(journal), encoding="utf-8")
        # A power loss can leave some files still original, some replaced,
        # and some new files not yet copied. All must be recoverable.
        old.write_bytes(b"original")
        (self.root / "www/portalai-live-v0.5.12.js").unlink()
        installer.rollback(self.root, backup)
        self.assertEqual(old.read_bytes(), b"original")
        self.assertFalse((self.root / "custom_components/portalai_projection/__init__.py").exists())
        self.assert_private_preserved()

    def test_bad_id_missing_config_traversal_and_lock_refused(self):
        with self.assertRaisesRegex(ValueError, "device-id"):
            installer.payload(self.package, "../private")
        with self.assertRaisesRegex(ValueError, "configuration directory"):
            installer.target_root(self.package)
        for value in ("../other", "/absolute", "C:/escape", "www/../configuration.yaml", "www\\escape"):
            with self.assertRaises(ValueError):
                installer.within(self.root, value)
        lock = self.root / ".portalai-installer/install.lock"
        lock.parent.mkdir()
        lock.write_text("12345", encoding="ascii")
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual(lock.read_text(), "12345")
        self.assertFalse((self.root / "www").exists())

    def test_symlink_or_junction_target_refused(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        link = self.root / "www"
        if sys.platform == "win32":
            # cmd's mklink only creates this isolated test junction; no delete/move.
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)], capture_output=True)
            if result.returncode:
                self.skipTest("Cannot create test junction")
        else:
            link.symlink_to(external, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "Linked paths"):
                self.install()
            self.assertEqual(list(external.iterdir()), [])
        finally:
            if sys.platform == "win32":
                link.rmdir()
            else:
                link.unlink()


if __name__ == "__main__":
    unittest.main()
