"""Tests for the build-time plugin mechanism (config, discovery, emission)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestBuildConfig(unittest.TestCase):
    def test_build_plugins_default_empty(self):
        out = lintc._normalize_build_config(None)
        self.assertEqual(out, {"plugins": {}})

    def test_build_plugins_passthrough(self):
        out = lintc._normalize_build_config({"plugins": {"lintc-swiper": {}}})
        self.assertEqual(out["plugins"], {"lintc-swiper": {}})

    def test_build_plugins_wrong_type_raises(self):
        with self.assertRaises(lintc.BuildError):
            lintc._normalize_build_config({"plugins": ["not-a-mapping"]})

    def test_build_config_round_trip_via_load_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "src" / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "site.yaml").write_text("title: t\n", encoding="utf-8")
            # Use an empty plugins map so load_config succeeds without a real plugin installed.
            (data_dir / "lintc.yaml").write_text(
                "build:\n  plugins: {}\n", encoding="utf-8"
            )
            cfg = lintc.load_config(root)
            self.assertEqual(cfg.build["plugins"], {})
            self.assertEqual(cfg.build_plugins, {})
            self.assertEqual(cfg.build_partials, {})


class TestBuildPluginDiscovery(unittest.TestCase):
    def test_returns_dict_of_modules_with_contract(self):
        found = lintc.discover_build_plugins()
        self.assertIsInstance(found, dict)
        for slug, mod in found.items():
            self.assertIsInstance(slug, str)
            self.assertTrue(hasattr(mod, "SHORTCODE"))
            self.assertTrue(hasattr(mod, "ASSETS"))

    def test_check_only_plugin_not_discovered_as_build(self):
        # remote-sync exposes run() but no SHORTCODE/ASSETS -> not a build plugin.
        found = lintc.discover_build_plugins()
        self.assertNotIn("remote-sync", found)


class TestSetupAndValidation(unittest.TestCase):
    def _cfg(self, build):
        return lintc.Config(
            "/tmp/x", {}, {}, {"email_allowlist": [], "stray_markers": [], "plugins": {}},
            build=build,
        )

    def test_enabled_unknown_plugin_raises(self):
        cfg = self._cfg({"plugins": {"does-not-exist": {}}})
        with self.assertRaises(lintc.BuildError):
            lintc._setup_build_plugins(cfg)

    def test_no_plugins_is_noop(self):
        cfg = self._cfg({"plugins": {}})
        lintc._setup_build_plugins(cfg)  # must not raise
        self.assertEqual(cfg.build_plugins, {})
        self.assertEqual(cfg.build_partials, {})


if __name__ == "__main__":
    unittest.main()
