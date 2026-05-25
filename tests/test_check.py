"""Tests for the check command's logic."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc



class TestConfigDrivenLayer1(unittest.TestCase):
    """v0.2: _validate_post_emit reads stray_markers + email_allowlist from cfg.check."""

    def _make_cfg_with_dist(self, root, check_config):
        """Make a Config pointing at a temp dist with HTML files for validation."""
        (root / "dist").mkdir()
        cfg = lintc.Config(
            root=root,
            site={},
            data={},
            check=check_config,
        )
        return cfg

    def test_email_allowlist_empty_disables_email_check(self):
        """With empty email_allowlist, foreign emails do NOT produce errors."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._make_cfg_with_dist(root, {
                "email_allowlist": [],
                "stray_markers": [],
                "plugins": {},
            })
            (cfg.dist / "page.html").write_text(
                '<html><a href="mailto:foo@example.com">x</a></html>'
            )
            errors, warnings = lintc._validate_post_emit(cfg, mode="build")
            self.assertEqual([e for e in errors if "email" in e.lower()], [],
                "no email check should run with empty allowlist")

    def test_email_allowlist_flags_foreign(self):
        """With allowlist ['@example.com'], emails not matching are errors."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._make_cfg_with_dist(root, {
                "email_allowlist": ["@example.com"],
                "stray_markers": [],
                "plugins": {},
            })
            (cfg.dist / "page.html").write_text(
                '<html><a href="mailto:bad@other.com">x</a></html>'
            )
            errors, warnings = lintc._validate_post_emit(cfg, mode="build")
            self.assertTrue(any("bad@other.com" in e for e in errors),
                "foreign email should be flagged")

    def test_email_allowlist_allows_matching(self):
        """An email ending with an allowlist entry is OK."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._make_cfg_with_dist(root, {
                "email_allowlist": ["@example.com"],
                "stray_markers": [],
                "plugins": {},
            })
            (cfg.dist / "page.html").write_text(
                '<html><a href="mailto:ok@example.com">x</a></html>'
            )
            errors, warnings = lintc._validate_post_emit(cfg, mode="build")
            self.assertEqual([e for e in errors if "email" in e.lower()], [],
                "matching email should not be flagged")

    def test_stray_markers_empty_disables_check(self):
        """With empty stray_markers, even literal TODO does NOT error."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._make_cfg_with_dist(root, {
                "email_allowlist": [],
                "stray_markers": [],
                "plugins": {},
            })
            (cfg.dist / "page.html").write_text("<html>TODO: ship this</html>")
            errors, warnings = lintc._validate_post_emit(cfg, mode="build")
            self.assertEqual([e for e in errors if "stray" in e.lower()], [],
                "no stray-marker check should run with empty list")

    def test_stray_markers_custom_list(self):
        """Custom stray_markers list overrides defaults."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._make_cfg_with_dist(root, {
                "email_allowlist": [],
                "stray_markers": ["DRAFT"],
                "plugins": {},
            })
            (cfg.dist / "page.html").write_text("<html>DRAFT — not ready</html>")
            errors, warnings = lintc._validate_post_emit(cfg, mode="build")
            self.assertTrue(any("DRAFT" in e for e in errors))
            # And TODO is NOT flagged (it's not in the custom list)
            (cfg.dist / "other.html").write_text("<html>TODO</html>")
            errors, warnings = lintc._validate_post_emit(cfg, mode="build")
            todos = [e for e in errors if "TODO" in e and "stray" in e.lower()]
            self.assertEqual(todos, [], "TODO is not in custom stray_markers list")


class TestRunCheckPluginInvocation(unittest.TestCase):
    """v0.2: run_check loops over enabled plugins and merges their results."""

    def test_no_plugins_configured_means_no_plugins_run(self):
        """With check.plugins = {}, no plugins are invoked."""
        # Use the minimal fixture; cfg.check has empty plugins dict.
        fixture = Path(__file__).resolve().parent / "fixtures" / "minimal" / "input"
        cfg = lintc.load_config(fixture)
        # The default lintc.yaml in the fixture has no plugins; load_config
        # returns cfg with cfg.check.plugins = {}.
        errors, warnings = lintc.run_check(cfg)
        # No plugin errors should appear when no plugins are configured.
        plugin_errors = [e for e in errors if ":" in e and e.split(":")[0].replace("-", "_") in lintc.discover_plugins()]
        self.assertEqual(plugin_errors, [])

    def test_unknown_plugin_slug_raises_clear_error(self):
        """If lintc.yaml references a plugin slug that's not discovered, BuildError with helpful message."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "content").mkdir(parents=True)
            (root / "src" / "data").mkdir(parents=True)
            (root / "src" / "data" / "lintc.yaml").write_text("""\
check:
  plugins:
    nonexistent-plugin:
      foo: bar
""")
            cfg = lintc.load_config(root)
            with self.assertRaises(lintc.BuildError) as ctx:
                lintc.run_check(cfg)
            msg = str(ctx.exception)
            self.assertIn("nonexistent-plugin", msg)
            self.assertIn("not found", msg.lower())
            # Should also list available plugins
            self.assertIn("remote-sync", msg)


class TestRunCheckPluginOrdering(unittest.TestCase):
    """v0.3.1: plugins run BEFORE the build so plugins that write files
    (e.g., remote-sync) make their output available to render_page's
    body_source resolution."""

    def test_plugin_writes_body_source_file_before_build_reads_it(self):
        """A plugin that writes a body_source file lets the subsequent build succeed."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "content" / "pages").mkdir(parents=True)
            (root / "src" / "layouts").mkdir(parents=True)
            (root / "src" / "data").mkdir(parents=True)
            (root / "src" / "data" / "site.yaml").write_text("author: Test\n")
            # Page references body_source pointing at a file that doesn't exist yet.
            (root / "src" / "content" / "pages" / "home.yaml").write_text(
                "title: Home\nslug: home\ndescription: Home page\nbody_source: synced/from-plugin.md\n"
            )
            (root / "src" / "layouts" / "home.html").write_text(
                "<html><body>{{ page.body_html | raw }}</body></html>"
            )

            # A test-only plugin that writes the body_source file when invoked.
            # We register it ad-hoc by patching discover_plugins.
            def writing_plugin(cfg, plugin_config):
                target = cfg.src / "synced" / "from-plugin.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# Hello from plugin\n")
                return [], []

            # Config invokes the test plugin.
            (root / "src" / "data" / "lintc.yaml").write_text(
                "check:\n  plugins:\n    test-writer:\n      foo: bar\n"
            )
            cfg = lintc.load_config(root)
            from unittest.mock import patch
            with patch.object(lintc, "discover_plugins",
                              return_value={"test-writer": writing_plugin}):
                errors, warnings = lintc.run_check(cfg)
            # If plugins ran AFTER build, body_source would have errored.
            # The fact that we got here without exception means plugin ran first.
            # Filter out unrelated build noise; just check no body_source errors.
            body_source_errors = [e for e in errors if "body_source" in e]
            self.assertEqual(body_source_errors, [],
                "body_source should resolve because plugin wrote the file before build ran")
