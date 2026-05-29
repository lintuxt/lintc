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


if __name__ == "__main__":
    unittest.main()
