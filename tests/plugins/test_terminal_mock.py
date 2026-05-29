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
