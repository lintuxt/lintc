"""Tests for page.body_sections — h2-based section splitting of body_source HTML (v0.4.0)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


def _make_site(root, body_md_text):
    """Helper: minimal site with one yaml page using body_source.

    `body_md_text=None` means no body_source (page has no body file).
    """
    (root / "src" / "content" / "pages").mkdir(parents=True)
    (root / "src" / "data").mkdir(parents=True)
    (root / "src" / "layouts").mkdir(parents=True)
    (root / "src" / "data" / "site.yaml").write_text("author: Test\n")
    if body_md_text is None:
        (root / "src" / "content" / "pages" / "home.yaml").write_text(
            "title: Home\nslug: home\ndescription: A home page.\n"
        )
    else:
        (root / "src" / "content" / "pages" / "home.yaml").write_text(
            "title: Home\nslug: home\ndescription: A home page.\nbody_source: synced/body.md\n"
        )
        (root / "src" / "synced").mkdir(parents=True, exist_ok=True)
        (root / "src" / "synced" / "body.md").write_text(body_md_text)
    (root / "src" / "layouts" / "home.html").write_text(
        "<html><body>{{ page.body_html | raw }}</body></html>"
    )


def _render_home(root):
    """Build and return the home page object after render_page runs."""
    cfg = lintc.load_config(root)
    pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
    home = [p for p in pages if p.slug == "home"][0]
    lintc.render_page(cfg, home, pages)
    return home


class TestSplitBodyHtmlByH2(unittest.TestCase):
    """Unit tests for the helper directly."""

    def test_empty_body_returns_empty_dict(self):
        self.assertEqual(lintc._split_body_html_by_h2(""), {})

    def test_body_without_h2_returns_empty_dict(self):
        html = "<p>Just a paragraph.</p>\n<p>Another one.</p>"
        self.assertEqual(lintc._split_body_html_by_h2(html), {})

    def test_single_h2_section(self):
        html = "<h2>Install</h2>\n<p>Run this.</p>"
        result = lintc._split_body_html_by_h2(html)
        self.assertEqual(set(result.keys()), {"Install"})
        self.assertIn("<p>Run this.</p>", result["Install"])

    def test_multiple_h2_sections(self):
        html = (
            "<h2>Install</h2>\n<p>brew install thing</p>\n"
            "<h2>Quickstart</h2>\n<p>thing --help</p>\n"
            "<h2>License</h2>\n<p>MIT</p>"
        )
        result = lintc._split_body_html_by_h2(html)
        self.assertEqual(set(result.keys()), {"Install", "Quickstart", "License"})
        self.assertIn("brew install thing", result["Install"])
        self.assertIn("thing --help", result["Quickstart"])
        self.assertIn("MIT", result["License"])

    def test_content_before_first_h2_discarded(self):
        """Preamble (tagline, badges, intro paragraphs) is not in any section."""
        html = (
            "<p><em>A tagline.</em></p>\n"
            "<p><img alt='badge' src='x'></p>\n"
            "<h2>Install</h2>\n<p>install steps</p>"
        )
        result = lintc._split_body_html_by_h2(html)
        self.assertEqual(set(result.keys()), {"Install"})
        # The tagline + badge are NOT in the Install section value
        self.assertNotIn("tagline", result["Install"])
        self.assertNotIn("badge", result["Install"])

    def test_inline_markup_in_heading_is_stripped_from_key(self):
        """## Install <code>solcito</code> → key is 'Install solcito' (tags stripped)."""
        html = "<h2>Install <code>solcito</code></h2>\n<p>x</p>"
        result = lintc._split_body_html_by_h2(html)
        # Inline tags stripped; whitespace preserved between text fragments
        self.assertEqual(set(result.keys()), {"Install solcito"})

    def test_duplicate_h2_last_wins(self):
        """Two ## Install sections: the second's body is what body_sections['Install'] returns."""
        html = (
            "<h2>Install</h2>\n<p>first install</p>\n"
            "<h2>Install</h2>\n<p>second install</p>"
        )
        result = lintc._split_body_html_by_h2(html)
        self.assertEqual(set(result.keys()), {"Install"})
        self.assertIn("second install", result["Install"])
        self.assertNotIn("first install", result["Install"])

    def test_section_with_code_blocks_and_paragraphs(self):
        """Sections preserve full inner HTML — code blocks, paragraphs, lists, etc."""
        html = (
            "<h2>Install</h2>\n"
            "<pre><code>brew install thing</code></pre>\n"
            "<p>Downloads the latest release.</p>\n"
            "<ul><li>step one</li><li>step two</li></ul>\n"
            "<h2>Next</h2>\n<p>done</p>"
        )
        result = lintc._split_body_html_by_h2(html)
        install = result["Install"]
        self.assertIn("<pre><code>brew install thing</code></pre>", install)
        self.assertIn("<p>Downloads the latest release.</p>", install)
        self.assertIn("<li>step one</li>", install)
        # Next-section content NOT in Install
        self.assertNotIn("done", install)

    def test_h2_value_excludes_the_heading_itself(self):
        """body_sections['Install'] does NOT contain '<h2>Install</h2>'."""
        html = "<h2>Install</h2>\n<p>steps</p>"
        result = lintc._split_body_html_by_h2(html)
        self.assertNotIn("<h2>", result["Install"])
        self.assertNotIn("</h2>", result["Install"])
        self.assertIn("<p>steps</p>", result["Install"])


class TestBodySectionsIntegration(unittest.TestCase):
    """Integration: full page render exposes body_sections in scope."""

    def test_page_with_body_source_has_both_body_html_and_body_sections(self):
        body_md = (
            "*Tagline.*\n\n"
            "## Install\n\n"
            "Run `brew install thing`.\n\n"
            "## Quickstart\n\n"
            "Then run `thing --help`.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, body_md)
            home = _render_home(root)
        # body_html: full rendered markdown (v0.3 behavior — unchanged)
        self.assertIn("<h2>Install</h2>", home.body_html)
        self.assertIn("Tagline", home.body_html)
        # body_sections: parsed dict
        self.assertIn("Install", home.body_sections)
        self.assertIn("Quickstart", home.body_sections)
        self.assertIn("brew install thing", home.body_sections["Install"])
        self.assertIn("thing --help", home.body_sections["Quickstart"])
        # Tagline is preamble — not in any section
        for v in home.body_sections.values():
            self.assertNotIn("Tagline", v)

    def test_page_without_body_source_has_empty_body_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, None)  # no body_source
            home = _render_home(root)
        self.assertEqual(home.body_sections, {})
        self.assertEqual(home.body_html, "")

    def test_body_source_with_no_h2_yields_empty_body_sections_but_full_body_html(self):
        """A README that's all preamble with no ## headings: body_html has the content,
        body_sections is empty."""
        body_md = "Just a paragraph.\n\nAnother paragraph.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, body_md)
            home = _render_home(root)
        self.assertIn("Just a paragraph.", home.body_html)
        self.assertEqual(home.body_sections, {})


if __name__ == "__main__":
    unittest.main()


class TestTemplateBracketAccess(unittest.TestCase):
    """Templates can access body_sections via bracket syntax: page.body_sections["Heading"]."""

    def test_template_bracket_access_simple_key(self):
        body_md = "## Install\n\n`brew install thing`\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, body_md)
            # Replace layout with one that uses bracket access
            (root / "src" / "layouts" / "home.html").write_text(
                '<div>{{ page.body_sections["Install"] | raw }}</div>'
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            rendered = lintc.render_page(cfg, home, pages)
        self.assertIn("brew install thing", rendered)

    def test_template_bracket_access_key_with_spaces(self):
        body_md = "## Why it exists\n\nBecause reasons.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, body_md)
            (root / "src" / "layouts" / "home.html").write_text(
                '<div>{{ page.body_sections["Why it exists"] | raw }}</div>'
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            rendered = lintc.render_page(cfg, home, pages)
        self.assertIn("Because reasons.", rendered)

    def test_template_bracket_access_in_if(self):
        body_md = "## Install\n\nInstall instructions.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_site(root, body_md)
            (root / "src" / "layouts" / "home.html").write_text(
                '{{ if page.body_sections["Install"] }}<p>has install</p>{{ end }}'
                '{{ if page.body_sections["Missing"] }}<p>has missing</p>{{ end }}'
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            rendered = lintc.render_page(cfg, home, pages)
        self.assertIn("<p>has install</p>", rendered)
        self.assertNotIn("<p>has missing</p>", rendered)


class TestSplitPath(unittest.TestCase):
    """Unit tests for the path splitter."""

    def test_plain_dot_path(self):
        self.assertEqual(lintc._tpl_split_path("page.body_html"), ["page", "body_html"])

    def test_bracket_simple_key(self):
        self.assertEqual(
            lintc._tpl_split_path('page.body_sections["Install"]'),
            ["page", "body_sections", "Install"],
        )

    def test_bracket_key_with_spaces(self):
        self.assertEqual(
            lintc._tpl_split_path('page.body_sections["Why it exists"]'),
            ["page", "body_sections", "Why it exists"],
        )

    def test_bracket_single_quotes(self):
        self.assertEqual(
            lintc._tpl_split_path("page.body_sections['Install']"),
            ["page", "body_sections", "Install"],
        )

    def test_bracket_then_dot(self):
        self.assertEqual(
            lintc._tpl_split_path('a.b["c d"].e'),
            ["a", "b", "c d", "e"],
        )
