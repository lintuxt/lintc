"""Tests for the bundled tag-sync plugin."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import lintc
import lintc_plugins.tag_sync as tag_sync


def _make_cfg(root):
    (root / "src" / "data").mkdir(parents=True, exist_ok=True)
    return lintc.Config(
        root=root,
        site={},
        data={},
        check={"email_allowlist": [], "stray_markers": [], "plugins": {}},
    )


class TestTagSyncConfig(unittest.TestCase):
    def test_missing_mappings_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, warnings = tag_sync.run(_make_cfg(Path(tmp)), {})
        self.assertEqual(len(errors), 1)
        self.assertIn("mappings", errors[0])

    def test_non_list_mappings_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, warnings = tag_sync.run(_make_cfg(Path(tmp)), {"mappings": {}})
        self.assertEqual(len(errors), 1)
        self.assertIn("mappings", errors[0])

    def test_empty_mappings_silent_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, warnings = tag_sync.run(_make_cfg(Path(tmp)), {"mappings": []})
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


class TestSelectLatestTag(unittest.TestCase):
    def test_picks_highest_semver(self):
        tags = ["v0.1.5", "v0.1.10", "v0.2.0", "v0.1.9"]
        self.assertEqual(tag_sync._select_latest_tag(tags), "v0.2.0")

    def test_numeric_ordering_not_lexical(self):
        self.assertEqual(tag_sync._select_latest_tag(["v0.1.9", "v0.1.10"]), "v0.1.10")

    def test_skips_prereleases(self):
        tags = ["v1.0.0", "v1.1.0-rc1", "v1.0.5-beta"]
        self.assertEqual(tag_sync._select_latest_tag(tags), "v1.0.0")

    def test_ignores_non_semver(self):
        tags = ["latest", "nightly", "v2.3.4", "qmk-0.32"]
        self.assertEqual(tag_sync._select_latest_tag(tags), "v2.3.4")

    def test_empty_or_no_semver_returns_none(self):
        self.assertIsNone(tag_sync._select_latest_tag([]))
        self.assertIsNone(tag_sync._select_latest_tag(["latest", "v1.0.0-rc1"]))


class TestRewriteField(unittest.TestCase):
    def test_rewrites_version_line(self):
        text = "title: lintc\nslug: lintc\nversion: v0.1.3\nbody_source: synced/lintc.md\n"
        out = tag_sync._rewrite_field(text, "version", "v0.7.0")
        self.assertIn("version: v0.7.0\n", out)
        self.assertNotIn("v0.1.3", out)
        self.assertIn("title: lintc\n", out)
        self.assertIn("body_source: synced/lintc.md\n", out)

    def test_does_not_match_prefixed_key(self):
        text = "language_versions: \"6.0+\"\nversion: v0.1.0\n"
        out = tag_sync._rewrite_field(text, "version", "v0.1.1")
        self.assertIn('language_versions: "6.0+"\n', out)
        self.assertIn("version: v0.1.1\n", out)

    def test_no_version_line_returns_none(self):
        text = "title: x\nslug: x\n"
        self.assertIsNone(tag_sync._rewrite_field(text, "version", "v1.0.0"))

    def test_value_with_special_chars_is_literal(self):
        text = "version: old\n"
        out = tag_sync._rewrite_field(text, "version", "v1.0.0")
        self.assertEqual(out, "version: v1.0.0\n")


class TestFetchTagsParsing(unittest.TestCase):
    def test_parses_ls_remote_output_skipping_deref(self):
        sample = (
            "deadbeef\trefs/tags/v0.1.0\n"
            "cafef00d\trefs/tags/v0.2.0\n"
            "cafef00d\trefs/tags/v0.2.0^{}\n"
        )
        with patch.object(tag_sync.subprocess, "run") as m:
            m.return_value = type("R", (), {"returncode": 0, "stdout": sample})()
            tags = tag_sync._fetch_tags("lintuxt/foo")
        self.assertEqual(sorted(tags), ["v0.1.0", "v0.2.0"])

    def test_fetch_returns_none_on_nonzero(self):
        with patch.object(tag_sync.subprocess, "run") as m:
            m.return_value = type("R", (), {"returncode": 128, "stdout": ""})()
            self.assertIsNone(tag_sync._fetch_tags("lintuxt/foo"))

    def test_fetch_returns_none_on_oserror(self):
        with patch.object(tag_sync.subprocess, "run", side_effect=OSError):
            self.assertIsNone(tag_sync._fetch_tags("lintuxt/foo"))


class TestRunBehavior(unittest.TestCase):
    def _yaml(self, root, rel, body):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_sets_version_and_writes_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            f = self._yaml(root, "src/content/products/foo.yaml",
                           "title: Foo\nslug: foo\nversion: v0.1.0\n")
            with patch.object(tag_sync, "_latest_tag", return_value="v0.2.0"):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [{"repo": "lintuxt/foo",
                                  "local": "src/content/products/foo.yaml"}],
                })
            self.assertEqual(errors, [])
            self.assertIn("version: v0.2.0\n", f.read_text())
            lock = root / "src/data/lintc-tag.lock"
            self.assertTrue(lock.exists())
            self.assertIn("v0.2.0", lock.read_text())
            self.assertTrue(any("set version to v0.2.0" in w for w in warnings))

    def test_no_change_when_already_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            f = self._yaml(root, "src/content/products/foo.yaml", "version: v0.2.0\n")
            before = f.read_text()
            with patch.object(tag_sync, "_latest_tag", return_value="v0.2.0"):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [{"repo": "lintuxt/foo",
                                  "local": "src/content/products/foo.yaml"}],
                })
            self.assertEqual(f.read_text(), before)
            self.assertFalse(any("set version" in w for w in warnings))

    def test_fetch_failure_leaves_field_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            f = self._yaml(root, "src/content/products/foo.yaml", "version: v0.1.0\n")
            with patch.object(tag_sync, "_latest_tag", return_value=None):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [{"repo": "lintuxt/foo",
                                  "local": "src/content/products/foo.yaml"}],
                })
            self.assertIn("version: v0.1.0\n", f.read_text())
            self.assertTrue(any("no tag fetched" in w for w in warnings))

    def test_missing_version_line_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            self._yaml(root, "src/content/products/foo.yaml", "title: Foo\nslug: foo\n")
            with patch.object(tag_sync, "_latest_tag", return_value="v0.2.0"):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [{"repo": "lintuxt/foo",
                                  "local": "src/content/products/foo.yaml"}],
                })
            self.assertEqual(errors, [])
            self.assertTrue(any("no top-level `version:` line" in w for w in warnings))

    def test_missing_file_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            with patch.object(tag_sync, "_latest_tag", return_value="v0.2.0"):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [{"repo": "lintuxt/foo",
                                  "local": "src/content/products/missing.yaml"}],
                })
            self.assertTrue(any("does not exist" in w for w in warnings))

    def test_one_bad_mapping_does_not_abort_others(self):
        # A mapping missing `repo` errors, but a valid mapping still processes.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            good = self._yaml(root, "src/content/products/good.yaml",
                              "version: v0.1.0\n")
            with patch.object(tag_sync, "_latest_tag", return_value="v0.2.0"):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [
                        {"local": "src/content/products/bad.yaml"},   # missing repo
                        {"repo": "lintuxt/good",
                         "local": "src/content/products/good.yaml"},
                    ],
                })
            # the bad mapping produced an error...
            self.assertTrue(any("missing required" in e for e in errors))
            # ...but the good one still got its version set
            self.assertIn("version: v0.2.0\n", good.read_text())

    def test_stale_lock_entry_refreshed_without_rewriting_file(self):
        # File already current, but the lockfile records an older tag → lock is
        # refreshed (no file rewrite, no "set version" warning).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            f = self._yaml(root, "src/content/products/foo.yaml", "version: v0.2.0\n")
            before = f.read_text()
            (root / "src/data/lintc-tag.lock").write_text(
                "version: 1\nentries:\n"
                "  src/content/products/foo.yaml:\n"
                "    repo: \"lintuxt/foo\"\n"
                "    tag: \"v0.1.0\"\n"
                "    fetched_at: 2026-01-01T00:00:00Z\n",
                encoding="utf-8",
            )
            with patch.object(tag_sync, "_latest_tag", return_value="v0.2.0"):
                errors, warnings = tag_sync.run(cfg, {
                    "mappings": [{"repo": "lintuxt/foo",
                                  "local": "src/content/products/foo.yaml"}],
                })
            self.assertEqual(f.read_text(), before)  # file untouched
            self.assertFalse(any("set version" in w for w in warnings))
            # lock now records the current tag
            self.assertIn("v0.2.0", (root / "src/data/lintc-tag.lock").read_text())


if __name__ == "__main__":
    unittest.main()
