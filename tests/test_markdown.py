"""Unit tests for the Markdown subset parser."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestParagraphs(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(lintc.markdown_render(""), "")

    def test_single_paragraph(self):
        self.assertEqual(
            lintc.markdown_render("hello world"),
            "<p>hello world</p>",
        )

    def test_multiline_paragraph(self):
        self.assertEqual(
            lintc.markdown_render("line one\nline two"),
            "<p>line one\nline two</p>",
        )

    def test_two_paragraphs(self):
        self.assertEqual(
            lintc.markdown_render("first.\n\nsecond."),
            "<p>first.</p>\n<p>second.</p>",
        )


class TestHeadings(unittest.TestCase):
    def test_h1(self):
        self.assertEqual(lintc.markdown_render("# Title"), "<h1>Title</h1>")

    def test_h2(self):
        self.assertEqual(lintc.markdown_render("## Section"), "<h2>Section</h2>")

    def test_h6(self):
        self.assertEqual(lintc.markdown_render("###### Tiny"), "<h6>Tiny</h6>")

    def test_heading_then_paragraph(self):
        self.assertEqual(
            lintc.markdown_render("## Where my work is now\n\nLike a lot of engineers."),
            "<h2>Where my work is now</h2>\n<p>Like a lot of engineers.</p>",
        )


class TestLists(unittest.TestCase):
    def test_unordered_list(self):
        text = "- one\n- two\n- three"
        self.assertEqual(
            lintc.markdown_render(text),
            "<ul>\n<li>one</li>\n<li>two</li>\n<li>three</li>\n</ul>",
        )

    def test_ordered_list(self):
        text = "1. one\n2. two\n3. three"
        self.assertEqual(
            lintc.markdown_render(text),
            "<ol>\n<li>one</li>\n<li>two</li>\n<li>three</li>\n</ol>",
        )

    def test_list_with_star_marker(self):
        text = "* one\n* two"
        self.assertEqual(
            lintc.markdown_render(text),
            "<ul>\n<li>one</li>\n<li>two</li>\n</ul>",
        )

    def test_nested_unordered(self):
        text = "- one\n  - one.a\n  - one.b\n- two"
        self.assertEqual(
            lintc.markdown_render(text),
            (
                "<ul>\n"
                "<li>one\n<ul>\n<li>one.a</li>\n<li>one.b</li>\n</ul>\n</li>\n"
                "<li>two</li>\n"
                "</ul>"
            ),
        )


class TestBlocks(unittest.TestCase):
    def test_fenced_code_block(self):
        text = "```\nplain code\n```"
        self.assertEqual(
            lintc.markdown_render(text),
            "<pre><code>plain code\n</code></pre>",
        )

    def test_fenced_code_with_language(self):
        text = "```python\ndef foo(): pass\n```"
        self.assertEqual(
            lintc.markdown_render(text),
            '<pre><code class="language-python">def foo(): pass\n</code></pre>',
        )

    def test_blockquote(self):
        self.assertEqual(
            lintc.markdown_render("> quoted text"),
            "<blockquote>quoted text</blockquote>",
        )

    def test_multiline_blockquote(self):
        self.assertEqual(
            lintc.markdown_render("> first line\n> second line"),
            "<blockquote>first line\nsecond line</blockquote>",
        )

    def test_horizontal_rule(self):
        self.assertEqual(lintc.markdown_render("---"), "<hr>")

    def test_code_block_preserves_html(self):
        # HTML inside a code block must be escaped.
        text = "```\n<div>hi</div>\n```"
        self.assertEqual(
            lintc.markdown_render(text),
            "<pre><code>&lt;div&gt;hi&lt;/div&gt;\n</code></pre>",
        )

    def test_raw_html_block_passthrough(self):
        # CommonMark §4.6 HTML block (type 6): a block starting with a
        # block-level HTML tag is passed through verbatim, not wrapped in <p>.
        text = '<p style="color:red">hello <strong>world</strong></p>'
        self.assertEqual(
            lintc.markdown_render(text),
            '<p style="color:red">hello <strong>world</strong></p>',
        )

    def test_raw_html_div_block_passthrough(self):
        text = '<div class="callout">inner text</div>'
        self.assertEqual(
            lintc.markdown_render(text),
            '<div class="callout">inner text</div>',
        )

    def test_inline_lt_not_treated_as_html_block(self):
        # A paragraph starting with "<3" or similar inline text must NOT be
        # mistaken for an HTML block — only block-level tag names trigger.
        # (Lone `<` is HTML-escaped to `&lt;` by the inline renderer.)
        text = "I love <3 you"
        self.assertEqual(
            lintc.markdown_render(text),
            "<p>I love &lt;3 you</p>",
        )


class TestInlines(unittest.TestCase):
    def test_bold(self):
        self.assertEqual(
            lintc.markdown_render("**hello**"),
            "<p><strong>hello</strong></p>",
        )

    def test_italic(self):
        self.assertEqual(
            lintc.markdown_render("*hello*"),
            "<p><em>hello</em></p>",
        )

    def test_inline_code(self):
        self.assertEqual(
            lintc.markdown_render("press `Ctrl-C`"),
            "<p>press <code>Ctrl-C</code></p>",
        )

    def test_link(self):
        self.assertEqual(
            lintc.markdown_render("[text](https://example.com)"),
            '<p><a href="https://example.com">text</a></p>',
        )

    def test_image(self):
        self.assertEqual(
            lintc.markdown_render("![alt](/img.png)"),
            '<p><img src="/img.png" alt="alt"></p>',
        )

    def test_bold_inside_paragraph(self):
        self.assertEqual(
            lintc.markdown_render("I deliver **production** software."),
            "<p>I deliver <strong>production</strong> software.</p>",
        )

    def test_italic_in_running_text(self):
        self.assertEqual(
            lintc.markdown_render("building *with* AI"),
            "<p>building <em>with</em> AI</p>",
        )

    def test_raw_html_passthrough(self):
        self.assertEqual(
            lintc.markdown_render("Contact <a href=\"mailto:me@lintuxt.ai\">me</a>."),
            '<p>Contact <a href="mailto:me@lintuxt.ai">me</a>.</p>',
        )

    def test_html_escape_outside_html(self):
        # < and > that aren't tags get escaped.
        self.assertEqual(
            lintc.markdown_render("5 < 10"),
            "<p>5 &lt; 10</p>",
        )

    def test_inline_code_escapes_html(self):
        self.assertEqual(
            lintc.markdown_render("look at `<script>`"),
            "<p>look at <code>&lt;script&gt;</code></p>",
        )


class TestShortcodes(unittest.TestCase):
    SC_OPEN = "\x00SC"
    SC_CLOSE = "\x00"

    def test_self_closing_inline(self):
        invocations = []
        out = lintc.markdown_render(
            'See {{< youtube id="abc" />}}.',
            _invocations=invocations,
        )
        # Self-closing inline → sentinel token embedded in paragraph.
        self.assertIn("<p>See ", out)
        self.assertIn("\x00SC", out)
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0]["name"], "youtube")

    def test_paired_inline(self):
        invocations = []
        out = lintc.markdown_render(
            "Look at {{< highlight >}}this{{< /highlight >}} text.",
            _invocations=invocations,
        )
        self.assertIn("<p>Look at ", out)
        self.assertEqual(invocations[0]["name"], "highlight")

    def test_paired_block(self):
        text = "{{< callout >}}\nThe hub is **three** things.\n{{< /callout >}}"
        invocations = []
        out = lintc.markdown_render(text, _invocations=invocations)
        # Block context: NOT wrapped in <p>. Output is a sentinel token.
        self.assertTrue(out.startswith("\x00SC"))
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0]["name"], "callout")
        # Inner should have been rendered through _md_render_block (paragraph).
        self.assertIn("<p>The hub is <strong>three</strong> things.</p>", invocations[0]["inner"])

    def test_paired_block_with_attributes(self):
        text = '{{< callout variant="warn" >}}\nBe careful.\n{{< /callout >}}'
        invocations = []
        lintc.markdown_render(text, _invocations=invocations)
        self.assertEqual(invocations[0]["attrs"].get("variant"), "warn")  # attrs in invocations

    def test_shortcode_inside_list(self):
        invocations = []
        text = "- normal item\n- {{< highlight >}}fancy{{< /highlight >}} item"
        out = lintc.markdown_render(text, _invocations=invocations)
        self.assertIn("<ul>", out)
        self.assertEqual(invocations[0]["name"], "highlight")


if __name__ == "__main__":
    unittest.main()
