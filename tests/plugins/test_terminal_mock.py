"""Tests for the bundled terminal-mock plugin."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import lintc  # noqa: E402
import lintc_plugins.terminal_mock as tm  # noqa: E402

ESC = "\x1b"


class TestAnsiToSpans(unittest.TestCase):
    def test_plain_text_is_unwrapped_and_escaped(self):
        html, warnings = tm.ansi_to_spans("a < b & c")
        self.assertEqual(html, "a &lt; b &amp; c")
        self.assertEqual(warnings, [])

    def test_single_code_wraps_in_class(self):
        html, _ = tm.ansi_to_spans(f"{ESC}[96m1{ESC}[0m")
        self.assertEqual(html, '<span class="t-cyan">1</span>')

    def test_bold_plus_brightcyan_is_name(self):
        html, _ = tm.ansi_to_spans(f"{ESC}[1m{ESC}[96mdisplayswitcher{ESC}[0m")
        self.assertEqual(html, '<span class="t-name">displayswitcher</span>')

    def test_reset_returns_to_plain(self):
        html, _ = tm.ansi_to_spans(f"{ESC}[2m·{ESC}[0m x")
        self.assertEqual(html, '<span class="t-faint">·</span> x')

    def test_unknown_code_warns_and_passes_through(self):
        html, warnings = tm.ansi_to_spans(f"{ESC}[31mboom{ESC}[0m")
        self.assertEqual(html, "boom")
        self.assertEqual(len(warnings), 1)
        self.assertIn("31", warnings[0])

    def test_combined_escape_sequence(self):
        # Defensive: a single escape carrying both codes (`\x1b[1;96m`) must
        # resolve the same as two separate escapes. CLIKit emits the separate
        # form, but the converter should not depend on that.
        html, _ = tm.ansi_to_spans(f"{ESC}[1;96mtext{ESC}[0m")
        self.assertEqual(html, '<span class="t-name">text</span>')

    def test_bare_reset_escape(self):
        # `\x1b[m` (empty params) is an SGR reset and must clear styling.
        html, warnings = tm.ansi_to_spans(f"{ESC}[96mx{ESC}[mtail")
        self.assertEqual(html, '<span class="t-cyan">x</span>tail')
        self.assertEqual(warnings, [])


class TestWrapChrome(unittest.TestCase):
    def test_wraps_body_with_prompt_and_cursor(self):
        body = '  <span class="t-cyan">x</span>'
        result = tm.wrap_chrome(body, command="displayswitcher")
        self.assertIn("Last login:", result)
        # command appears on the leading prompt's command line
        self.assertIn('<span class="t-dim">$ </span>displayswitcher', result)
        # the captured body is present verbatim
        self.assertIn(body, result)
        # trailing prompt + cursor close the frame
        self.assertIn('<span class="t-cursor" aria-hidden="true"></span>', result)
        # body sits between the two prompts
        self.assertLess(result.index(body), result.rindex("$ "))


_SAMPLE_YAML = (
    "title: foo\n"
    "terminal:\n"
    '  aria_label: "x"\n'
    "  body_html: |-\n"
    "    OLD LINE A\n"
    "\n"
    "    OLD LINE B\n"
    "\n"
    "features:\n"
    "  - name: List\n"
)


class TestReplaceBodyHtml(unittest.TestCase):
    def test_replaces_only_block_content(self):
        new = tm.replace_body_html(_SAMPLE_YAML, ["NEW 1", "", "NEW 2"])
        self.assertIn("  body_html: |-\n", new)
        self.assertIn("    NEW 1\n", new)
        self.assertIn("    NEW 2\n", new)
        self.assertNotIn("OLD LINE", new)
        # blank lines inside the block stay blank (no stray indentation)
        self.assertIn("    NEW 1\n\n    NEW 2\n", new)
        # surrounding structure intact, trailing blank before features kept
        self.assertIn('  aria_label: "x"\n', new)
        self.assertIn("\nfeatures:\n", new)

    def test_idempotent(self):
        once = tm.replace_body_html(_SAMPLE_YAML, ["NEW 1", "", "NEW 2"])
        twice = tm.replace_body_html(once, ["NEW 1", "", "NEW 2"])
        self.assertEqual(once, twice)

    def test_missing_block_returns_none(self):
        self.assertIsNone(tm.replace_body_html("title: foo\n", ["x"]))
