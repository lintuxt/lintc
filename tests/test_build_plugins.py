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


class TestBuildPluginContract(unittest.TestCase):
    def setUp(self):
        import lintc_plugins
        self.pkg_dir = Path(lintc_plugins.__path__[0])
        self.mod_path = self.pkg_dir / "partialless.py"
        # SHORTCODE + ASSETS but NO PARTIAL
        self.mod_path.write_text(
            "SHORTCODE = 'partialless'\nASSETS = []\n", encoding="utf-8")

    def tearDown(self):
        if self.mod_path.exists():
            self.mod_path.unlink()
        sys.modules.pop("lintc_plugins.partialless", None)

    def test_module_without_partial_not_discovered(self):
        found = lintc.discover_build_plugins()
        self.assertNotIn("partialless", found)


class TestEmissionAndInjection(unittest.TestCase):
    def setUp(self):
        import lintc_plugins
        self.pkg_dir = Path(lintc_plugins.__path__[0])
        self.asset_dir = self.pkg_dir / "_fixture_assets"
        self.asset_dir.mkdir(exist_ok=True)
        (self.asset_dir / "component.html").write_text(
            '<div class="fix">{{ inner | raw }}</div>', encoding="utf-8")
        (self.asset_dir / "fix.css").write_text(".fix{}", encoding="utf-8")
        (self.asset_dir / "fix.js").write_text("/*fix*/", encoding="utf-8")
        # Discovery skips names starting with "_", so name the module without one.
        self.mod_path = self.pkg_dir / "fixtureswiper.py"
        self.mod_path.write_text(
            "from pathlib import Path\n"
            "_H = Path(__file__).resolve().parent / '_fixture_assets'\n"
            "SHORTCODE = 'fixtureswiper'\n"
            "PARTIAL = _H / 'component.html'\n"
            "ASSETS = [_H / 'fix.css', _H / 'fix.js']\n",
            encoding="utf-8",
        )

    def tearDown(self):
        for p in [self.mod_path,
                  self.asset_dir / "component.html",
                  self.asset_dir / "fix.css",
                  self.asset_dir / "fix.js"]:
            if p.exists():
                p.unlink()
        if self.asset_dir.exists():
            self.asset_dir.rmdir()
        sys.modules.pop("lintc_plugins.fixtureswiper", None)

    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-bp-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def _site_files(self, body_uses_shortcode):
        body = ("{{< fixtureswiper >}}\n<figure>x</figure>\n{{< /fixtureswiper >}}"
                if body_uses_shortcode else "plain body")
        return {
            "src/data/site.yaml": "title: t\nbase_url: https://e.test",
            "src/data/lintc.yaml": "build:\n  plugins:\n    fixtureswiper: {}\n",
            "src/layouts/_base.html": "<html><body>{{ inner | raw }}</body></html>",
            "src/layouts/blog-post.html": '{{ layout "_base.html" }}{{ page.body_html | raw }}',
            "src/content/blog/a.md": "---\ntitle: A\ndescription: d\n---\n" + body,
        }

    def test_assets_emitted_and_tags_injected_when_used(self):
        root = self._make_site(self._site_files(True))
        result = lintc.build_site(root)
        self.assertEqual(result.errors, [], result.errors)
        js = root / "dist/assets/plugins/fixtureswiper/fix.js"
        css = root / "dist/assets/plugins/fixtureswiper/fix.css"
        self.assertTrue(js.exists() and css.exists())
        html = (root / "dist/blog/a/index.html").read_text()
        self.assertIn('/assets/plugins/fixtureswiper/fix.css', html)
        self.assertIn('/assets/plugins/fixtureswiper/fix.js', html)
        self.assertIn('<div class="fix">', html)  # partial resolved

    def test_no_assets_or_tags_when_unused(self):
        root = self._make_site(self._site_files(False))
        result = lintc.build_site(root)
        self.assertEqual(result.errors, [], result.errors)
        self.assertFalse((root / "dist/assets/plugins/fixtureswiper").exists())
        html = (root / "dist/blog/a/index.html").read_text()
        self.assertNotIn('/assets/plugins/fixtureswiper/', html)


if __name__ == "__main__":
    unittest.main()
