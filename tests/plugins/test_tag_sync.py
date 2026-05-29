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


if __name__ == "__main__":
    unittest.main()
