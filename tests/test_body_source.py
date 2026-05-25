"""Tests for the body_source page field (v0.3.0)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


def _make_site(root, page_yaml_text, body_md_text=None, body_md_path="synced/body.md"):
    """Helper: minimal site with one yaml page + optional body source md file."""
    (root / "src" / "content" / "pages").mkdir(parents=True)
    (root / "src" / "data").mkdir(parents=True)
    (root / "src" / "layouts").mkdir(parents=True)
    (root / "src" / "data" / "site.yaml").write_text("author: Test\n")
    (root / "src" / "content" / "pages" / "home.yaml").write_text(page_yaml_text)
    (root / "src" / "layouts" / "home.html").write_text(
        "<html><body>{{ page.body_html | raw }}</body></html>"
    )
    if body_md_text is not None:
        full_path = root / "src" / body_md_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body_md_text)


class TestBodySource(unittest.TestCase):
    def test_yaml_page_with_body_source_renders_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(
                root,
                "title: Home\nslug: home\ndescription: A home page.\nbody_source: synced/body.md\n",
                body_md_text="# Hello\n\nThis is **bold** text.\n",
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            html = lintc.render_page(cfg, home, pages)
        self.assertIn("<h1>Hello</h1>", html)
        self.assertIn("<strong>bold</strong>", html)

    def test_yaml_page_without_body_source_has_empty_body_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, "title: Home\nslug: home\ndescription: A home page.\n")
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            html = lintc.render_page(cfg, home, pages)
        self.assertIn("<body></body>", html.replace(" ", "").replace("\n", ""))

    def test_body_source_missing_file_raises_builderror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(
                root,
                "title: Home\nslug: home\ndescription: A home page.\nbody_source: synced/does-not-exist.md\n",
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            with self.assertRaises(lintc.BuildError) as ctx:
                lintc.render_page(cfg, home, pages)
            msg = str(ctx.exception)
            self.assertIn("body_source", msg)
            self.assertIn("does-not-exist.md", msg)

    def test_md_page_with_both_inline_body_and_body_source_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "content" / "blog").mkdir(parents=True)
            (root / "src" / "data").mkdir(parents=True)
            (root / "src" / "layouts").mkdir(parents=True)
            (root / "src" / "data" / "site.yaml").write_text("author: Test\n")
            (root / "src" / "synced").mkdir(parents=True)
            (root / "src" / "synced" / "body.md").write_text("# External body\n")
            (root / "src" / "content" / "blog" / "post.md").write_text(
                "---\ntitle: A Post\ndescription: A blog post.\nbody_source: synced/body.md\n---\n\n"
                "# Inline body\n\nThis should not coexist with body_source.\n"
            )
            (root / "src" / "layouts" / "blog-post.html").write_text(
                "<html><body>{{ page.body_html | raw }}</body></html>"
            )
            cfg = lintc.load_config(root)
            with self.assertRaises(lintc.BuildError) as ctx:
                lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            msg = str(ctx.exception)
            self.assertIn("body_source", msg)
            self.assertIn("inline body", msg.lower())

    def test_body_source_relative_to_src(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(
                root,
                "title: Home\nslug: home\ndescription: A home page.\nbody_source: synced/body.md\n",
                body_md_text="Some content.\n",
                body_md_path="synced/body.md",
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            html = lintc.render_page(cfg, home, pages)
        self.assertIn("Some content.", html)


if __name__ == "__main__":
    unittest.main()
