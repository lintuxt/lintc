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
        self.assertEqual(html, '<span class="t-accent">1</span>')

    def test_bold_plus_brightcyan_is_strong(self):
        html, _ = tm.ansi_to_spans(f"{ESC}[1m{ESC}[96mdisplayswitcher{ESC}[0m")
        self.assertEqual(html, '<span class="t-strong">displayswitcher</span>')

    def test_reset_returns_to_plain(self):
        html, _ = tm.ansi_to_spans(f"{ESC}[2m·{ESC}[0m x")
        self.assertEqual(html, '<span class="t-subtle">·</span> x')

    def test_unknown_code_warns_and_passes_through(self):
        html, warnings = tm.ansi_to_spans(f"{ESC}[34mboom{ESC}[0m")
        self.assertEqual(html, "boom")
        self.assertEqual(len(warnings), 1)
        self.assertIn("34", warnings[0])

    def test_combined_escape_sequence(self):
        # Defensive: a single escape carrying both codes (`\x1b[1;96m`) must
        # resolve the same as two separate escapes. CLIKit emits the separate
        # form, but the converter should not depend on that.
        html, _ = tm.ansi_to_spans(f"{ESC}[1;96mtext{ESC}[0m")
        self.assertEqual(html, '<span class="t-strong">text</span>')

    def test_bare_reset_escape(self):
        # `\x1b[m` (empty params) is an SGR reset and must clear styling.
        html, warnings = tm.ansi_to_spans(f"{ESC}[96mx{ESC}[mtail")
        self.assertEqual(html, '<span class="t-accent">x</span>tail')
        self.assertEqual(warnings, [])


class TestSemanticColors(unittest.TestCase):
    def test_green_is_ok(self):
        html, w = tm.ansi_to_spans(f"{ESC}[32m✓{ESC}[0m")
        self.assertEqual(html, '<span class="t-ok">✓</span>'); self.assertEqual(w, [])

    def test_yellow_is_warn(self):
        html, w = tm.ansi_to_spans(f"{ESC}[33m(asleep){ESC}[0m")
        self.assertEqual(html, '<span class="t-warn">(asleep)</span>'); self.assertEqual(w, [])

    def test_red_is_error(self):
        html, w = tm.ansi_to_spans(f"{ESC}[31mlow{ESC}[0m")
        self.assertEqual(html, '<span class="t-error">low</span>'); self.assertEqual(w, [])

    def test_other_semantics(self):
        self.assertEqual(tm.ansi_to_spans(f"{ESC}[90mv1{ESC}[0m")[0], '<span class="t-muted">v1</span>')
        self.assertEqual(tm.ansi_to_spans(f"{ESC}[97mX{ESC}[0m")[0], '<span class="t-strong">X</span>')
        self.assertEqual(tm.ansi_to_spans(f"{ESC}[36mU{ESC}[0m")[0], '<span class="t-link">U</span>')
        self.assertEqual(tm.ansi_to_spans(f"{ESC}[35m♥{ESC}[0m")[0], '<span class="t-love">♥</span>')


class TestTrimBlankEdges(unittest.TestCase):
    def test_strips_edge_blanks_keeps_internal(self):
        self.assertEqual(
            tm._trim_blank_edges("\n\n  a\n\n  b\n\n"), "  a\n\n  b")

    def test_all_blank_becomes_empty(self):
        self.assertEqual(tm._trim_blank_edges("\n  \n\n"), "")


class TestWrapChrome(unittest.TestCase):
    def test_wraps_body_with_prompt_and_cursor(self):
        body = '  <span class="t-cyan">x</span>'
        result = tm.wrap_chrome(body, command="displayswitcher")
        self.assertIn("Last login:", result)
        # command appears on the leading prompt's command line
        self.assertIn('<span class="t-muted">$ </span>displayswitcher', result)
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


class TestCapturePty(unittest.TestCase):
    def test_child_sees_a_tty(self):
        out, rc = tm.capture_under_pty(
            [sys.executable, "-c",
             "import os,sys; sys.stdout.write('TTY' if os.isatty(1) else 'PIPE')"],
            env_extra={},
            columns=120,
        )
        self.assertEqual(rc, 0)
        self.assertIn("TTY", out)

    def test_env_extra_is_passed(self):
        out, rc = tm.capture_under_pty(
            [sys.executable, "-c",
             "import os,sys; sys.stdout.write(os.environ.get('LINTUXT_DEBUG','none'))"],
            env_extra={"LINTUXT_DEBUG": "1"},
            columns=120,
        )
        self.assertEqual(rc, 0)
        self.assertIn("1", out)


def _make_cfg(root):
    (root / "src" / "data").mkdir(parents=True, exist_ok=True)
    return lintc.Config(
        root=root, site={}, data={},
        check={"email_allowlist": [], "stray_markers": [], "plugins": {}},
    )


class TestRun(unittest.TestCase):
    def test_missing_mappings_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, _ = tm.run(_make_cfg(Path(tmp)), {})
        self.assertEqual(len(errors), 1)
        self.assertIn("mappings", errors[0])

    def test_empty_mappings_silent_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, warnings = tm.run(_make_cfg(Path(tmp)), {"mappings": []})
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_binary_warns_and_leaves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            target = root / "page.yaml"
            target.write_text(_SAMPLE_YAML, encoding="utf-8")
            errors, warnings = tm.run(cfg, {"mappings": [
                {"command": "definitely-not-a-real-binary-xyz", "local": "page.yaml"},
            ]})
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("not found", warnings[0])
            self.assertEqual(target.read_text(encoding="utf-8"), _SAMPLE_YAML)

    def test_end_to_end_with_stub_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _make_cfg(root)
            target = root / "page.yaml"
            target.write_text(_SAMPLE_YAML, encoding="utf-8")
            stub = root / "fakecli"
            stub.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                r"sys.stdout.write('\x1b[96mhi\x1b[0m')" + "\n",
                encoding="utf-8",
            )
            os.chmod(stub, 0o755)
            errors, warnings = tm.run(cfg, {"mappings": [
                {"command": str(stub), "local": "page.yaml"},
            ]})
            self.assertEqual(errors, [])
            text = target.read_text(encoding="utf-8")
            self.assertIn('<span class="t-accent">hi</span>', text)
            self.assertIn("Last login:", text)
            self.assertTrue((root / "src" / "data" / "lintc-terminal.lock").exists())

    def test_non_list_args_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, _ = tm.run(_make_cfg(Path(tmp)), {"mappings": [
                {"command": "x", "local": "page.yaml", "args": "--help"},
            ]})
        self.assertEqual(len(errors), 1)
        self.assertIn("args", errors[0])
