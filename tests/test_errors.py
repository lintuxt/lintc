"""Tests for the error message contract (§10.2 of the spec)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestSuggestions(unittest.TestCase):
    def test_did_you_mean_for_undefined_variable(self):
        with self.assertRaises(lintc.TemplateError) as ctx:
            lintc.template_render("{{ titel }}", {"title": "Hi"})
        self.assertIn("did you mean", str(ctx.exception))
        self.assertIn("title", str(ctx.exception))

    def test_no_suggestion_when_nothing_close(self):
        with self.assertRaises(lintc.TemplateError) as ctx:
            lintc.template_render("{{ zzzz }}", {"title": "Hi"})
        self.assertNotIn("did you mean", str(ctx.exception))

    def test_did_you_mean_for_undefined_filter(self):
        with self.assertRaises(lintc.TemplateError) as ctx:
            lintc.template_render("{{ x | uppr }}", {"x": "hi"})
        self.assertIn("did you mean", str(ctx.exception))
        self.assertIn("upper", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
