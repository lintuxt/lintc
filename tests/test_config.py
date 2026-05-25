"""Tests for src/data/lintc.yaml loading and validation (v0.2.0)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


def _make_site_with_lintc_yaml(root, lintc_yaml_text):
    """Helper: create a minimal site tree with src/data/lintc.yaml content."""
    (root / "src" / "data").mkdir(parents=True)
    (root / "src" / "content").mkdir(parents=True)
    if lintc_yaml_text is not None:
        (root / "src" / "data" / "lintc.yaml").write_text(lintc_yaml_text)


class TestLintcYamlLoading(unittest.TestCase):
    def test_missing_file_yields_defaults(self):
        """No lintc.yaml: cfg.check has all defaults (stray_markers ON, no email_allowlist, no plugins)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, None)
            cfg = lintc.load_config(root)
            self.assertEqual(
                set(cfg.check["stray_markers"]),
                {"TODO", "FIXME", "PLACEHOLDER", "lorem ipsum"},
                "missing lintc.yaml should still enable default stray_markers",
            )
            self.assertEqual(cfg.check["email_allowlist"], [])
            self.assertEqual(cfg.check["plugins"], {})

    def test_full_config_loaded(self):
        """Full lintc.yaml: every field reachable on cfg.check."""
        yaml_text = """\
check:
  email_allowlist:
    - "@example.com"
  stray_markers:
    - "TODO"
    - "DRAFT"
  plugins:
    remote-sync:
      repo_url: "https://github.com/example/repo"
      branch: main
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, yaml_text)
            cfg = lintc.load_config(root)
            self.assertEqual(cfg.check["email_allowlist"], ["@example.com"])
            self.assertEqual(cfg.check["stray_markers"], ["TODO", "DRAFT"])
            self.assertIn("remote-sync", cfg.check["plugins"])
            self.assertEqual(cfg.check["plugins"]["remote-sync"]["branch"], "main")

    def test_empty_stray_markers_disables_check(self):
        """stray_markers: [] means 'I want no stray-marker check at all' (different from missing key)."""
        yaml_text = """\
check:
  stray_markers: []
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, yaml_text)
            cfg = lintc.load_config(root)
            self.assertEqual(cfg.check["stray_markers"], [])

    def test_missing_stray_markers_uses_defaults(self):
        """Missing stray_markers key (or null) defaults to the built-in list."""
        yaml_text = """\
check:
  email_allowlist: ["@example.com"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, yaml_text)
            cfg = lintc.load_config(root)
            self.assertEqual(
                set(cfg.check["stray_markers"]),
                {"TODO", "FIXME", "PLACEHOLDER", "lorem ipsum"},
            )

    def test_email_allowlist_default_is_empty(self):
        """Missing email_allowlist = empty list = OFF."""
        yaml_text = """\
check:
  stray_markers: ["TODO"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, yaml_text)
            cfg = lintc.load_config(root)
            self.assertEqual(cfg.check["email_allowlist"], [])

    def test_type_mismatch_email_allowlist_raises(self):
        """email_allowlist as a string (not a list) is a hard error."""
        yaml_text = """\
check:
  email_allowlist: "@example.com"
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, yaml_text)
            with self.assertRaises(lintc.BuildError) as ctx:
                lintc.load_config(root)
            self.assertIn("email_allowlist", str(ctx.exception))
            self.assertIn("list", str(ctx.exception))

    def test_unknown_keys_under_check_emit_warning(self):
        """Unknown keys under check produce a stderr warning, not an error (forward-compat for v0.3+)."""
        import io
        from contextlib import redirect_stderr
        yaml_text = """\
check:
  email_allowlist: ["@example.com"]
  future_v03_feature: 42
  another_unknown: "foo"
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site_with_lintc_yaml(root, yaml_text)
            stderr_buf = io.StringIO()
            with redirect_stderr(stderr_buf):
                cfg = lintc.load_config(root)
            stderr_text = stderr_buf.getvalue()

        # No exception, config still loads cleanly.
        self.assertEqual(cfg.check["email_allowlist"], ["@example.com"])

        # Both unknown keys produce warnings.
        self.assertIn("future_v03_feature", stderr_text,
            "expected stderr warning for future_v03_feature; got: %r" % stderr_text)
        self.assertIn("another_unknown", stderr_text,
            "expected stderr warning for another_unknown; got: %r" % stderr_text)
        self.assertIn("ignoring unknown key", stderr_text)


if __name__ == "__main__":
    unittest.main()
