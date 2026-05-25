"""Tests for the bundled remote-sync plugin."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import lintc
import lintc_plugins.remote_sync as remote_sync


def _make_cfg(root):
    (root / "src" / "data").mkdir(parents=True, exist_ok=True)
    return lintc.Config(
        root=root,
        site={},
        data={},
        check={"email_allowlist": [], "stray_markers": [], "plugins": {}},
    )


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestRemoteSyncCore(unittest.TestCase):
    def test_missing_mappings_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            errors, warnings = remote_sync.run(cfg, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("mappings", errors[0])

    def test_empty_mappings_silent_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            errors, warnings = remote_sync.run(cfg, {"mappings": []})
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_initial_sync_writes_file_and_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            remote_url = "https://example.test/README.md"
            local_path = "src/synced/example.md"
            content = b"# Example\n\nHello.\n"
            with patch.object(remote_sync, "_fetch_url", return_value=content):
                errors, warnings = remote_sync.run(cfg, {
                    "mappings": [{"remote": remote_url, "local": local_path}],
                })
            written = (root / local_path).read_bytes()
            self.assertEqual(written, content)
            lockfile = root / "src" / "data" / "lintc-sync.lock"
            self.assertTrue(lockfile.exists())
            lock_data = lintc.yaml_parse(lockfile.read_text())
            self.assertIn(local_path, lock_data["entries"])
            self.assertEqual(lock_data["entries"][local_path]["sha256"], _sha("# Example\n\nHello.\n"))
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("initial sync", warnings[0])
        self.assertIn(local_path, warnings[0])

    def test_no_drift_silent_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            content = b"unchanged\n"
            local_path = "src/synced/static.md"
            (root / "src" / "synced").mkdir(parents=True)
            (root / local_path).write_bytes(content)
            (root / "src" / "data" / "lintc-sync.lock").write_text(
                "version: 1\nentries:\n  %s:\n    remote: https://example.test/x\n"
                "    sha256: %s\n    fetched_at: 2026-01-01T00:00:00Z\n"
                % (local_path, _sha("unchanged\n"))
            )
            mtime_before = (root / local_path).stat().st_mtime
            with patch.object(remote_sync, "_fetch_url", return_value=content):
                errors, warnings = remote_sync.run(cfg, {
                    "mappings": [{"remote": "https://example.test/x", "local": local_path}],
                })
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])
            self.assertEqual((root / local_path).stat().st_mtime, mtime_before)

    def test_drift_overwrites_file_and_updates_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            old_content = b"old version\n"
            new_content = b"new version\n"
            local_path = "src/synced/changing.md"
            (root / "src" / "synced").mkdir(parents=True)
            (root / local_path).write_bytes(old_content)
            (root / "src" / "data" / "lintc-sync.lock").write_text(
                "version: 1\nentries:\n  %s:\n    remote: https://example.test/x\n"
                "    sha256: %s\n    fetched_at: 2026-01-01T00:00:00Z\n"
                % (local_path, _sha("old version\n"))
            )
            with patch.object(remote_sync, "_fetch_url", return_value=new_content):
                errors, warnings = remote_sync.run(cfg, {
                    "mappings": [{"remote": "https://example.test/x", "local": local_path}],
                })
            self.assertEqual((root / local_path).read_bytes(), new_content)
            lock_data = lintc.yaml_parse((root / "src" / "data" / "lintc-sync.lock").read_text())
            self.assertEqual(lock_data["entries"][local_path]["sha256"], _sha("new version\n"))
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("synced", warnings[0])
        self.assertIn("upstream changed", warnings[0])

    def test_network_failure_emits_warning_for_that_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            content = b"ok\n"
            local_a = "src/synced/a.md"
            local_b = "src/synced/b.md"
            def _fetch(url):
                if "fail" in url:
                    return None
                return content
            with patch.object(remote_sync, "_fetch_url", side_effect=_fetch):
                errors, warnings = remote_sync.run(cfg, {
                    "mappings": [
                        {"remote": "https://example.test/fail", "local": local_a},
                        {"remote": "https://example.test/ok", "local": local_b},
                    ],
                })
            self.assertFalse((root / local_a).exists())
            self.assertTrue((root / local_b).exists())
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("could not fetch" in w for w in warnings))

    def test_message_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            with patch.object(remote_sync, "_fetch_url", return_value=b"x\n"):
                errors, warnings = remote_sync.run(cfg, {
                    "mappings": [{"remote": "https://example.test/x", "local": "src/synced/x.md"}],
                })
            for w in warnings:
                self.assertTrue(w.startswith("remote-sync:"), w)


class TestFetchUrl(unittest.TestCase):
    def test_returns_bytes_on_success(self):
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value.read.return_value = b"hello"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = remote_sync._fetch_url("https://example.test/x")
        self.assertEqual(result, b"hello")

    def test_returns_none_on_network_failure(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = remote_sync._fetch_url("https://example.test/x")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
