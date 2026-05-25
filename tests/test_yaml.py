"""Unit tests for the YAML subset parser in tools/lintc.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestScalars(unittest.TestCase):
    def test_empty_input(self):
        self.assertIsNone(lintc.yaml_parse(""))

    def test_whitespace_only(self):
        self.assertIsNone(lintc.yaml_parse("   \n  \n"))

    def test_plain_string(self):
        self.assertEqual(lintc.yaml_parse("hello"), "hello")

    def test_plain_string_with_spaces(self):
        self.assertEqual(lintc.yaml_parse("hello world"), "hello world")

    def test_double_quoted_string(self):
        self.assertEqual(lintc.yaml_parse('"hello world"'), "hello world")

    def test_double_quoted_escapes(self):
        self.assertEqual(lintc.yaml_parse(r'"line1\nline2"'), "line1\nline2")
        self.assertEqual(lintc.yaml_parse(r'"a\"b"'), 'a"b')
        self.assertEqual(lintc.yaml_parse(r'"a\tb"'), "a\tb")

    def test_single_quoted_string(self):
        self.assertEqual(lintc.yaml_parse("'hello'"), "hello")
        # Single quotes do NOT process \n escapes
        self.assertEqual(lintc.yaml_parse(r"'a\nb'"), r"a\nb")
        # Doubled single quote = literal single quote
        self.assertEqual(lintc.yaml_parse("'it''s'"), "it's")

    def test_integer(self):
        self.assertEqual(lintc.yaml_parse("42"), 42)
        self.assertEqual(lintc.yaml_parse("-7"), -7)
        self.assertEqual(lintc.yaml_parse("0"), 0)

    def test_float(self):
        self.assertEqual(lintc.yaml_parse("3.14"), 3.14)
        self.assertEqual(lintc.yaml_parse("-0.5"), -0.5)

    def test_boolean(self):
        self.assertIs(lintc.yaml_parse("true"), True)
        self.assertIs(lintc.yaml_parse("false"), False)

    def test_null(self):
        self.assertIsNone(lintc.yaml_parse("null"))
        self.assertIsNone(lintc.yaml_parse("~"))


class TestBlockMappings(unittest.TestCase):
    def test_single_pair(self):
        self.assertEqual(lintc.yaml_parse("name: solcito"), {"name": "solcito"})

    def test_multiple_pairs(self):
        text = "name: solcito\ntagline: macOS CLI\nversion: 0.1.2"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"name": "solcito", "tagline": "macOS CLI", "version": "0.1.2"},
        )

    def test_typed_values(self):
        text = "status: live\ncount: 42\nactive: true\nnote: null"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"status": "live", "count": 42, "active": True, "note": None},
        )

    def test_nested_mapping(self):
        text = "author:\n  name: Alexis\n  city: Austin"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"author": {"name": "Alexis", "city": "Austin"}},
        )

    def test_deeply_nested(self):
        text = "a:\n  b:\n    c: 42"
        self.assertEqual(lintc.yaml_parse(text), {"a": {"b": {"c": 42}}})

    def test_quoted_key(self):
        self.assertEqual(lintc.yaml_parse('"my key": v'), {"my key": "v"})

    def test_value_with_colon(self):
        # YAML rule: a colon followed by space splits; bare colon stays in value.
        self.assertEqual(
            lintc.yaml_parse('url: https://lintuxt.ai'),
            {"url": "https://lintuxt.ai"},
        )


class TestBlockSequences(unittest.TestCase):
    def test_flat_sequence(self):
        self.assertEqual(lintc.yaml_parse("- one\n- two\n- three"), ["one", "two", "three"])

    def test_sequence_with_typed_items(self):
        self.assertEqual(lintc.yaml_parse("- 1\n- 2\n- true\n- null"), [1, 2, True, None])

    def test_nested_sequence(self):
        text = "- - a\n  - b\n- - c"
        self.assertEqual(lintc.yaml_parse(text), [["a", "b"], ["c"]])

    def test_sequence_of_mappings(self):
        text = "- name: solcito\n  tier: free\n- name: displayswitcher\n  tier: free"
        self.assertEqual(
            lintc.yaml_parse(text),
            [
                {"name": "solcito", "tier": "free"},
                {"name": "displayswitcher", "tier": "free"},
            ],
        )

    def test_mapping_containing_sequence(self):
        text = "tags:\n  - swift\n  - macos\n  - cli"
        self.assertEqual(lintc.yaml_parse(text), {"tags": ["swift", "macos", "cli"]})

    def test_mapping_of_mapping_containing_sequence(self):
        text = "section:\n  children:\n    - a\n    - b"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"section": {"children": ["a", "b"]}},
        )

    def test_sequence_with_url_item(self):
        # A plain URL is a scalar, not a 'key: value' mapping.
        self.assertEqual(
            lintc.yaml_parse("- https://foo.com\n- bar"),
            ["https://foo.com", "bar"],
        )

    def test_sequence_item_with_colon_no_space(self):
        # `v1.0:latest` is a plain scalar; colon-without-space is not a separator.
        self.assertEqual(
            lintc.yaml_parse("- v1.0:latest"),
            ["v1.0:latest"],
        )


class TestBlockScalars(unittest.TestCase):
    def test_literal_preserves_newlines(self):
        text = "body: |\n  line one\n  line two\n  line three"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "line one\nline two\nline three\n"},
        )

    def test_folded_joins_with_spaces(self):
        text = "body: >\n  word one\n  word two\n  word three"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "word one word two word three\n"},
        )

    def test_folded_blank_line_becomes_newline(self):
        text = "body: >\n  para one\n\n  para two"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "para one\npara two\n"},
        )

    def test_literal_in_mapping_field(self):
        text = (
            "name: solcito\n"
            "intro: |\n"
            "  Native macOS CLI.\n"
            "  Built on IOKit HID.\n"
            "tier: free"
        )
        self.assertEqual(
            lintc.yaml_parse(text),
            {
                "name": "solcito",
                "intro": "Native macOS CLI.\nBuilt on IOKit HID.\n",
                "tier": "free",
            },
        )

    def test_literal_with_trailing_space_on_indicator(self):
        # Editor-stripped trailing space on `|` must not crash.
        text = "body: |  \n  line one\n  line two"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "line one\nline two\n"},
        )

    def test_literal_preserves_deeper_indent(self):
        text = "body: |\n  line one\n    deeper\n  back"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "line one\n  deeper\nback\n"},
        )

    def test_strip_chomp_removes_trailing_newline(self):
        # `|-` strips trailing newlines; default `|` keeps one trailing newline.
        text = "body: |-\n  line one\n  line two"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "line one\nline two"},
        )

    def test_strip_chomp_folded(self):
        # `>-` strips trailing newline from folded scalar.
        text = "body: >-\n  word one\n  word two"
        self.assertEqual(
            lintc.yaml_parse(text),
            {"body": "word one word two"},
        )

    def test_hash_in_block_scalar_body_is_literal(self):
        # YAML 1.2: # inside block scalar body is NOT a comment.
        # The previous parser stripped them, corrupting shell-style comments.
        text = (
            "commands: |-\n"
            "  solcito           # show your receiver\n"
            "  solcito --pair    # add a new device\n"
            "  solcito --help    # full help"
        )
        self.assertEqual(
            lintc.yaml_parse(text),
            {"commands": "solcito           # show your receiver\nsolcito --pair    # add a new device\nsolcito --help    # full help"},
        )


class TestFlowForms(unittest.TestCase):
    def test_flow_sequence_empty(self):
        self.assertEqual(lintc.yaml_parse("[]"), [])

    def test_flow_sequence_strings(self):
        self.assertEqual(lintc.yaml_parse("[swift, macos, cli]"), ["swift", "macos", "cli"])

    def test_flow_sequence_quoted_strings(self):
        self.assertEqual(
            lintc.yaml_parse('["HID++ protocol", swift]'),
            ["HID++ protocol", "swift"],
        )

    def test_flow_sequence_mixed_types(self):
        self.assertEqual(lintc.yaml_parse("[1, 2.5, true, null]"), [1, 2.5, True, None])

    def test_flow_mapping_empty(self):
        self.assertEqual(lintc.yaml_parse("{}"), {})

    def test_flow_mapping(self):
        self.assertEqual(
            lintc.yaml_parse("{ name: solcito, tier: free }"),
            {"name": "solcito", "tier": "free"},
        )

    def test_flow_in_block_field(self):
        text = "tags: [swift, macos, cli]"
        self.assertEqual(lintc.yaml_parse(text), {"tags": ["swift", "macos", "cli"]})

    def test_block_sequence_of_flow_mappings(self):
        text = "- { label: Home, href: / }\n- { label: Blog, href: /blog/ }"
        self.assertEqual(
            lintc.yaml_parse(text),
            [{"label": "Home", "href": "/"}, {"label": "Blog", "href": "/blog/"}],
        )

    def test_unterminated_flow_mapping_after_colon(self):
        # Truncated input after the colon must raise YamlError, not IndexError.
        with self.assertRaises(lintc.YamlError):
            lintc.yaml_parse("{a:")


class TestComments(unittest.TestCase):
    def test_full_line_comment(self):
        text = "# this is a comment\nname: solcito"
        self.assertEqual(lintc.yaml_parse(text), {"name": "solcito"})

    def test_trailing_comment(self):
        text = "name: solcito  # the CLI\nversion: 0.1.2"
        self.assertEqual(lintc.yaml_parse(text), {"name": "solcito", "version": "0.1.2"})

    def test_hash_inside_string_value(self):
        # A # without preceding space is part of the value.
        self.assertEqual(
            lintc.yaml_parse("color: '#08080c'"),
            {"color": "#08080c"},
        )


class TestYamlErrors(unittest.TestCase):
    def test_unterminated_double_quote(self):
        with self.assertRaises(lintc.YamlError) as ctx:
            lintc.yaml_parse('name: "unterminated')
        self.assertIn("quoted", str(ctx.exception).lower())

    def test_missing_colon(self):
        with self.assertRaises(lintc.YamlError):
            lintc.yaml_parse("name solcito\nversion: 0.1.2")

    def test_inconsistent_indent(self):
        text = "a:\n  b: 1\n   c: 2"
        with self.assertRaises(lintc.YamlError):
            lintc.yaml_parse(text)

    def test_unterminated_flow_sequence(self):
        with self.assertRaises(lintc.YamlError):
            lintc.yaml_parse("tags: [swift, macos")


if __name__ == "__main__":
    unittest.main()
