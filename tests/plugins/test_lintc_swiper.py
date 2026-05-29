"""Integration test for the bundled lintc-swiper build plugin."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import lintc


class TestLintcSwiperPlugin(unittest.TestCase):
    def test_discovered_with_contract(self):
        found = lintc.discover_build_plugins()
        self.assertIn("lintc-swiper", found)
        mod = found["lintc-swiper"]
        self.assertEqual(mod.SHORTCODE, "lintc-swiper")
        self.assertTrue(Path(mod.PARTIAL).exists())
        for a in mod.ASSETS:
            self.assertTrue(Path(a).exists(), "%s missing" % a)

    def test_shortcode_renders_and_ships_assets(self):
        d = tempfile.mkdtemp(prefix="lintc-swiper-test-")
        root = Path(d)
        files = {
            "src/data/site.yaml": "title: t\nbase_url: https://e.test",
            "src/data/lintc.yaml": "build:\n  plugins:\n    lintc-swiper: {}\n",
            "src/layouts/_base.html": "<html><body>{{ inner | raw }}</body></html>",
            "src/layouts/blog-post.html": '{{ layout "_base.html" }}{{ page.body_html | raw }}',
            "src/content/blog/a.md": (
                "---\ntitle: A\ndescription: d\n---\n"
                "{{< lintc-swiper >}}\n"
                '<figure><img src="https://example.com/x.jpg" alt="x"><figcaption>c</figcaption></figure>\n'
                "{{< /lintc-swiper >}}"
            ),
        }
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        result = lintc.build_site(root)
        self.assertEqual(result.errors, [], result.errors)
        html = (root / "dist/blog/a/index.html").read_text()
        self.assertIn('<div class="lintc-swiper">', html)
        self.assertIn("/assets/plugins/lintc-swiper/lintc-swiper.js", html)
        self.assertTrue((root / "dist/assets/plugins/lintc-swiper/lintc-swiper.js").exists())
        self.assertTrue((root / "dist/assets/plugins/lintc-swiper/lintc-swiper.css").exists())


if __name__ == "__main__":
    unittest.main()
