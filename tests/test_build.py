"""Unit tests for the build pipeline."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestFrontMatter(unittest.TestCase):
    def test_split_with_front_matter(self):
        text = "---\ntitle: Hi\n---\nbody text"
        meta, body = lintc.split_front_matter(text)
        self.assertEqual(meta, {"title": "Hi"})
        self.assertEqual(body, "body text")

    def test_split_without_front_matter(self):
        meta, body = lintc.split_front_matter("just body")
        self.assertEqual(meta, {})
        self.assertEqual(body, "just body")

    def test_empty_input(self):
        meta, body = lintc.split_front_matter("")
        self.assertEqual(meta, {})
        self.assertEqual(body, "")

    def test_front_matter_with_trailing_blank(self):
        text = "---\ntitle: Hi\n---\n\nbody"
        meta, body = lintc.split_front_matter(text)
        self.assertEqual(meta, {"title": "Hi"})
        self.assertEqual(body, "body")


class TestParsePage(unittest.TestCase):
    def test_parse_markdown_post(self):
        text = "---\ntitle: A post\ndate: 2026-05-21\n---\nHello **world**."
        page = lintc.parse_page_source(
            source_text=text,
            kind="md",
            rel_path="blog/a-post.md",
        )
        self.assertEqual(page.title, "A post")
        self.assertEqual(page.kind, "post")
        self.assertEqual(page.section, "blog")
        self.assertEqual(page.slug, "a-post")
        self.assertEqual(page.url, "/blog/a-post/")
        self.assertIn("<strong>world</strong>", page.body_html)

    def test_parse_yaml_product(self):
        text = "name: solcito\ntier: free"
        page = lintc.parse_page_source(
            source_text=text,
            kind="yaml",
            rel_path="products/solcito.yaml",
        )
        self.assertEqual(page.kind, "product")
        self.assertEqual(page.section, "products")
        self.assertEqual(page.slug, "solcito")
        self.assertEqual(page.url, "/products/solcito/")
        self.assertEqual(page.meta["name"], "solcito")
        self.assertEqual(page.body_html, "")

    def test_parse_section_index(self):
        text = "title: Writing\n"
        page = lintc.parse_page_source(
            source_text=text,
            kind="yaml",
            rel_path="blog/_index.yaml",
        )
        self.assertEqual(page.kind, "section-index")
        self.assertEqual(page.url, "/blog/")

    def test_parse_pages_home(self):
        text = "title: lintuxt\n"
        page = lintc.parse_page_source(
            source_text=text,
            kind="yaml",
            rel_path="pages/home.yaml",
        )
        self.assertEqual(page.url, "/")

    def test_parse_pages_404(self):
        text = "title: Not found\n"
        page = lintc.parse_page_source(
            source_text=text,
            kind="yaml",
            rel_path="pages/404.yaml",
        )
        self.assertEqual(page.url, "/404.html")
        self.assertEqual(page.output_path, "404.html")


import tempfile


class TestDiscovery(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_discover_finds_all_content(self):
        root = self._make_site({
            "src/content/pages/home.yaml": "title: lintuxt",
            "src/content/blog/_index.yaml": "title: Blog",
            "src/content/blog/post-a.md": "---\ntitle: A\n---\nbody",
            "src/content/products/solcito.yaml": "name: solcito",
            "src/data/site.yaml": "title: lintuxt",
            "src/data/nav.yaml": "primary: []",
        })
        cfg = lintc.load_config(root)
        self.assertEqual(cfg.site["title"], "lintuxt")
        self.assertIn("nav", cfg.data)
        pages = lintc.discover_pages(cfg)
        rel_paths = sorted(p.rel_path for p in pages)
        self.assertEqual(
            rel_paths,
            [
                "blog/_index.yaml",
                "blog/post-a.md",
                "pages/home.yaml",
                "products/solcito.yaml",
            ],
        )

    def test_discover_skips_hidden_and_underscore_dirs(self):
        root = self._make_site({
            "src/content/pages/home.yaml": "title: x",
            "src/content/.draft/ignored.md": "---\ntitle: hidden\n---\nbody",
            "src/data/site.yaml": "title: x",
        })
        cfg = lintc.load_config(root)
        pages = lintc.discover_pages(cfg)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].rel_path, "pages/home.yaml")


class TestDerive(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_missing_title_fails(self):
        root = self._make_site({
            "src/content/blog/no-title.md": "---\ndescription: x\n---\nbody",
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
        })
        cfg = lintc.load_config(root)
        pages = lintc.discover_pages(cfg)
        with self.assertRaises(lintc.BuildError) as ctx:
            lintc.derive_pages(cfg, pages)
        self.assertIn("title", str(ctx.exception))
        self.assertIn("no-title", str(ctx.exception))

    def test_missing_description_fails(self):
        root = self._make_site({
            "src/content/blog/no-desc.md": "---\ntitle: T\n---\nbody",
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
        })
        cfg = lintc.load_config(root)
        pages = lintc.discover_pages(cfg)
        with self.assertRaises(lintc.BuildError) as ctx:
            lintc.derive_pages(cfg, pages)
        self.assertIn("description", str(ctx.exception))

    def test_drafts_excluded_by_default(self):
        root = self._make_site({
            "src/content/blog/draft.md": "---\ntitle: D\ndescription: x\ndraft: true\n---\nbody",
            "src/content/blog/published.md": "---\ntitle: P\ndescription: x\n---\nbody",
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
        })
        cfg = lintc.load_config(root, include_drafts=False)
        pages = lintc.discover_pages(cfg)
        kept = lintc.derive_pages(cfg, pages)
        slugs = sorted(p.slug for p in kept)
        self.assertEqual(slugs, ["published"])

    def test_drafts_included_when_flag_set(self):
        root = self._make_site({
            "src/content/blog/draft.md": "---\ntitle: D\ndescription: x\ndraft: true\n---\nbody",
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
        })
        cfg = lintc.load_config(root, include_drafts=True)
        pages = lintc.discover_pages(cfg)
        kept = lintc.derive_pages(cfg, pages)
        self.assertEqual(len(kept), 1)

    def test_last_modified_falls_back_to_today(self):
        # Uncommitted source → today
        root = self._make_site({
            "src/content/blog/p.md": "---\ntitle: T\ndescription: x\n---\nbody",
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
        })
        cfg = lintc.load_config(root)
        pages = lintc.discover_pages(cfg)
        kept = lintc.derive_pages(cfg, pages)
        import datetime
        self.assertEqual(kept[0].last_modified, datetime.date.today())


class TestRender(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_render_picks_blog_post_layout(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/blog-post.html": (
                '{{ layout "_base.html" }}<article><h1>{{ page.title }}</h1></article>'
            ),
            "src/content/blog/a.md": "---\ntitle: A\ndescription: x\n---\nbody",
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        self.assertIn("<html>", html)
        self.assertIn("<h1>A</h1>", html)

    def test_render_picks_product_layout(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/product.html": (
                '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>'
                '<p>{{ page.meta.tagline }}</p>'
            ),
            "src/content/products/s.yaml": "title: solcito\ndescription: x\ntagline: macOS CLI",
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        self.assertIn("<h1>solcito</h1>", html)
        self.assertIn("<p>macOS CLI</p>", html)

    def test_render_pages_home(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": (
                '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>'
            ),
            "src/content/pages/home.yaml": "title: lintuxt\ndescription: x",
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        self.assertIn("<h1>lintuxt</h1>", html)

    def test_layout_front_matter_override(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/custom.html": (
                '{{ layout "_base.html" }}<custom>{{ page.title }}</custom>'
            ),
            "src/content/products/s.yaml": (
                "title: solcito\ndescription: x\nlayout: custom"
            ),
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        self.assertIn("<custom>solcito</custom>", html)

    def test_partial_called_from_layout(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": (
                '<html>{{ partial "head.html" }}{{ inner | raw }}</html>'
            ),
            "src/layouts/partials/head.html": "<title>{{ page.title }}</title>",
            "src/layouts/product.html": (
                '{{ layout "_base.html" }}<main>{{ page.title }}</main>'
            ),
            "src/content/products/s.yaml": "title: solcito\ndescription: x",
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        self.assertIn("<title>solcito</title>", html)
        self.assertIn("<main>solcito</main>", html)

    def test_shortcode_resolved_in_body(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/blog-post.html": (
                '{{ layout "_base.html" }}<article>{{ page.body_html | raw }}</article>'
            ),
            "src/layouts/partials/components/callout.html": (
                '<div class="callout">{{ inner | raw }}</div>'
            ),
            "src/content/blog/a.md": (
                "---\ntitle: A\ndescription: x\n---\n"
                "{{< callout >}}\nbe careful\n{{< /callout >}}"
            ),
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        self.assertIn('<div class="callout">', html)
        self.assertIn("be careful", html)


class TestBuildSite(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_full_build_writes_dist_files(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": (
                '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>'
            ),
            "src/layouts/product.html": (
                '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>'
            ),
            "src/content/pages/home.yaml": "title: lintuxt\ndescription: home",
            "src/content/products/s.yaml": "title: solcito\ndescription: cli",
            "src/static/robots.txt": "User-agent: *\n",
        })
        result = lintc.build_site(root)
        self.assertEqual(result.errors, [])
        index_path = root / "dist" / "index.html"
        product_path = root / "dist" / "products" / "s" / "index.html"
        robots_path = root / "dist" / "robots.txt"
        self.assertTrue(index_path.exists())
        self.assertTrue(product_path.exists())
        self.assertTrue(robots_path.exists())
        self.assertIn("<h1>lintuxt</h1>", index_path.read_text(encoding="utf-8"))
        self.assertIn("<h1>solcito</h1>", product_path.read_text(encoding="utf-8"))
        self.assertEqual(robots_path.read_text(encoding="utf-8"), "User-agent: *\n")

    def test_orphan_dist_files_are_pruned(self):
        root = self._make_site({
            "src/data/site.yaml": "title: x\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        (root / "dist").mkdir(exist_ok=True)
        orphan = root / "dist" / "orphan.html"
        orphan.write_text("nope", encoding="utf-8")
        lintc.build_site(root)
        self.assertFalse(orphan.exists())


class TestSitemap(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_sitemap_lists_all_non_draft_pages(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/layouts/blog-post.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/layouts/404.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/content/pages/home.yaml": "title: lintuxt\ndescription: x",
            "src/content/pages/404.yaml": "title: Not found\ndescription: x",
            "src/content/blog/a.md": "---\ntitle: A\ndescription: x\n---\nbody",
        })
        lintc.build_site(root)
        sitemap = (root / "dist" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://lintuxt.ai/", sitemap)
        self.assertIn("https://lintuxt.ai/blog/a/", sitemap)
        self.assertNotIn("404.html", sitemap)

    def test_sitemap_excludes_drafts(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/blog-post.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/content/blog/a.md": "---\ntitle: A\ndescription: x\n---\nbody",
            "src/content/blog/draft.md": "---\ntitle: D\ndescription: x\ndraft: true\n---\nbody",
        })
        lintc.build_site(root)
        sitemap = (root / "dist" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("/blog/a/", sitemap)
        self.assertNotIn("/blog/draft/", sitemap)


class TestPostEmit(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_broken_internal_link_fails_build(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": (
                '{{ layout "_base.html" }}<a href="/nope/">link</a>'
            ),
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        result = lintc.build_site(root)
        self.assertTrue(any("/nope/" in e for e in result.errors))

    def test_external_link_is_ignored(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": (
                '{{ layout "_base.html" }}<a href="https://example.com">x</a>'
            ),
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        result = lintc.build_site(root)
        self.assertEqual(result.errors, [])

    def test_stray_marker_fails_build(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<p>TODO</p>',
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        result = lintc.build_site(root)
        self.assertTrue(any("TODO" in e for e in result.errors))

    def test_foreign_email_fails_build(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/data/lintc.yaml": "check:\n  email_allowlist:\n    - '@lintuxt.ai'\n",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<p>contact@example.com</p>',
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        result = lintc.build_site(root)
        self.assertTrue(any("contact@example.com" in e for e in result.errors))

    def test_lintuxt_email_is_fine(self):
        root = self._make_site({
            "src/data/site.yaml": "title: lintuxt\nbase_url: https://lintuxt.ai",
            "src/data/lintc.yaml": "check:\n  email_allowlist:\n    - '@lintuxt.ai'\n",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<p>me@lintuxt.ai</p>',
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        result = lintc.build_site(root)
        self.assertEqual(result.errors, [])


import json


class TestBuildCache(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_cache_written_after_build(self):
        root = self._make_site({
            "src/data/site.yaml": "title: x\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        lintc.build_site(root)
        cache = json.loads((root / ".lintc-cache.json").read_text(encoding="utf-8"))
        self.assertEqual(cache["version"], 1)
        self.assertIn("pages/home.yaml", cache["files"])

    def test_unchanged_page_uses_cache(self):
        root = self._make_site({
            "src/data/site.yaml": "title: x\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/home.html": '{{ layout "_base.html" }}<h1>{{ page.title }}</h1>',
            "src/content/pages/home.yaml": "title: x\ndescription: x",
        })
        result1 = lintc.build_site(root)
        result2 = lintc.build_site(root)
        self.assertEqual(
            sorted(p.url for p in result1.pages_built),
            sorted(p.url for p in result2.pages_built),
        )


class TestGoldenMinimal(unittest.TestCase):
    """End-to-end: build the minimal fixture, diff against the golden tree."""

    def test_minimal_fixture_matches_golden(self):
        import shutil
        import tempfile
        fixture_root = Path(__file__).resolve().parent / "fixtures" / "minimal"
        input_dir = fixture_root / "input"
        expected_dir = fixture_root / "expected"
        with tempfile.TemporaryDirectory(prefix="lintc-golden-test-") as tmp:
            tmp_root = Path(tmp)
            shutil.copytree(input_dir, tmp_root / "src")
            result = lintc.build_site(tmp_root)
            self.assertEqual(result.errors, [], "build errors: %s" % result.errors)
            actual_dir = tmp_root / "dist"
            self._diff_trees(expected_dir, actual_dir)

    def _diff_trees(self, expected_root, actual_root):
        expected_files = {
            p.relative_to(expected_root).as_posix()
            for p in expected_root.rglob("*")
            if p.is_file()
        }
        actual_files = {
            p.relative_to(actual_root).as_posix()
            for p in actual_root.rglob("*")
            if p.is_file()
        }
        missing = expected_files - actual_files
        extra = actual_files - expected_files
        self.assertFalse(missing, "missing files in dist/: %s" % missing)
        self.assertFalse(extra, "unexpected files in dist/: %s" % extra)
        for rel in sorted(expected_files):
            exp = (expected_root / rel).read_text(encoding="utf-8")
            act = (actual_root / rel).read_text(encoding="utf-8")
            if exp != act:
                self.fail("contents differ for %s:\n  expected: %r\n  actual:   %r"
                          % (rel, exp[:200], act[:200]))


class TestNestedShortcodes(unittest.TestCase):
    def _make_site(self, files):
        d = tempfile.mkdtemp(prefix="lintc-test-")
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return Path(d)

    def test_block_shortcode_containing_inline_shortcode(self):
        root = self._make_site({
            "src/data/site.yaml": "title: x\nbase_url: https://lintuxt.ai",
            "src/layouts/_base.html": "<html>{{ inner | raw }}</html>",
            "src/layouts/blog-post.html": (
                '{{ layout "_base.html" }}<article>{{ page.body_html | raw }}</article>'
            ),
            "src/layouts/partials/components/callout.html": (
                '<div class="callout">{{ inner | raw }}</div>'
            ),
            "src/layouts/partials/components/highlight.html": (
                '<span class="hl">{{ inner | raw }}</span>'
            ),
            "src/content/blog/a.md": (
                "---\ntitle: A\ndescription: x\n---\n"
                "{{< callout >}}\nThis is {{< highlight >}}important{{< /highlight >}} text.\n{{< /callout >}}"
            ),
        })
        cfg = lintc.load_config(root)
        pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
        html = lintc.render_page(cfg, pages[0], pages)
        # Both wrappers must be present, no sentinels in output.
        self.assertIn('<div class="callout">', html)
        self.assertIn('<span class="hl">', html)
        self.assertIn("important", html)
        self.assertNotIn("\x00", html, "raw sentinel bytes leaked into output")
        self.assertNotIn(":highlight:", html, "raw sentinel text leaked into output")


if __name__ == "__main__":
    unittest.main()
