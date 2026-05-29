"""Unit tests for the mustache-style template engine."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestVariables(unittest.TestCase):
    def test_literal_text(self):
        self.assertEqual(lintc.template_render("hello", {}), "hello")

    def test_simple_var(self):
        self.assertEqual(
            lintc.template_render("hello {{ name }}", {"name": "world"}),
            "hello world",
        )

    def test_html_escape_by_default(self):
        self.assertEqual(
            lintc.template_render("{{ x }}", {"x": "<b>bold</b>"}),
            "&lt;b&gt;bold&lt;/b&gt;",
        )

    def test_raw_filter(self):
        self.assertEqual(
            lintc.template_render("{{ x | raw }}", {"x": "<b>bold</b>"}),
            "<b>bold</b>",
        )

    def test_dotted_path(self):
        scope = {"page": {"title": "Hi", "author": {"name": "Alexis"}}}
        self.assertEqual(
            lintc.template_render("{{ page.title }} by {{ page.author.name }}", scope),
            "Hi by Alexis",
        )

    def test_comments_stripped(self):
        self.assertEqual(
            lintc.template_render("a {{# comment #}}b", {}),
            "a b",
        )

    def test_missing_var_raises(self):
        with self.assertRaises(lintc.TemplateError):
            lintc.template_render("{{ nope }}", {})


import datetime


class TestFilters(unittest.TestCase):
    def test_upper(self):
        self.assertEqual(
            lintc.template_render("{{ x | upper }}", {"x": "hello"}),
            "HELLO",
        )

    def test_lower(self):
        self.assertEqual(
            lintc.template_render("{{ x | lower }}", {"x": "Hello"}),
            "hello",
        )

    def test_length_of_list(self):
        self.assertEqual(
            lintc.template_render("{{ x | length }}", {"x": [1, 2, 3]}),
            "3",
        )

    def test_join(self):
        self.assertEqual(
            lintc.template_render('{{ x | join ", " }}', {"x": ["a", "b", "c"]}),
            "a, b, c",
        )

    def test_default(self):
        self.assertEqual(
            lintc.template_render('{{ x | default "fallback" }}', {"x": None}),
            "fallback",
        )
        self.assertEqual(
            lintc.template_render('{{ x | default "fallback" }}', {"x": "real"}),
            "real",
        )

    def test_date(self):
        d = datetime.date(2026, 5, 21)
        self.assertEqual(
            lintc.template_render('{{ d | date "%Y-%m-%d" }}', {"d": d}),
            "2026-05-21",
        )

    def test_truncate(self):
        self.assertEqual(
            lintc.template_render('{{ x | truncate 5 }}', {"x": "hello world"}),
            "hello…",
        )

    def test_slug(self):
        self.assertEqual(
            lintc.template_render('{{ x | slug }}', {"x": "Hello World — Tildes!"}),
            "hello-world-tildes",
        )

    def test_markdown(self):
        self.assertEqual(
            lintc.template_render('{{ x | markdown | raw }}', {"x": "**bold**"}),
            "<p><strong>bold</strong></p>",
        )

    def test_filter_chain(self):
        self.assertEqual(
            lintc.template_render('{{ x | upper | truncate 3 }}', {"x": "hello"}),
            "HEL…",
        )


class TestLimitFilter(unittest.TestCase):
    def test_limit_takes_first_n(self):
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit 2 }}{{ x }}{{ end }}',
                {"xs": ["a", "b", "c", "d"]},
            ),
            "ab",
        )

    def test_limit_zero_yields_empty(self):
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit 0 }}{{ x }}{{ end }}',
                {"xs": ["a", "b", "c"]},
            ),
            "",
        )

    def test_limit_greater_than_length_returns_all(self):
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit 10 }}{{ x }}{{ end }}',
                {"xs": ["a", "b"]},
            ),
            "ab",
        )

    def test_limit_on_none_yields_empty(self):
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit 3 }}{{ x }}{{ end }}',
                {"xs": None},
            ),
            "",
        )

    def test_limit_negative_raises(self):
        with self.assertRaises(lintc.TemplateError):
            lintc.template_render(
                '{{ for x in xs | limit -1 }}{{ x }}{{ end }}',
                {"xs": ["a", "b"]},
            )

    def test_limit_non_integer_raises(self):
        with self.assertRaises(lintc.TemplateError):
            lintc.template_render(
                '{{ for x in xs | limit "two" }}{{ x }}{{ end }}',
                {"xs": ["a", "b"]},
            )


class TestForLoopFilters(unittest.TestCase):
    def test_for_loop_applies_filter_to_iterable(self):
        # Regression guard: for-loop iterables route through the filter path.
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit 2 }}{{ x }}{{ end }}',
                {"xs": ["a", "b", "c"]},
            ),
            "ab",
        )

    def test_for_loop_without_filter_still_works(self):
        # Regression guard: plain (unfiltered) for-loop iterables unchanged.
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs }}{{ x }}{{ end }}',
                {"xs": ["a", "b", "c"]},
            ),
            "abc",
        )

    def test_for_loop_dotted_path_iterable_still_works(self):
        self.assertEqual(
            lintc.template_render(
                '{{ for x in obj.items }}{{ x }}{{ end }}',
                {"obj": {"items": ["p", "q"]}},
            ),
            "pq",
        )

    def test_for_loop_key_value_iteration_still_works(self):
        # If lintc supports {{ for k, v in dict }}, this must still work.
        # If it does NOT support k,v iteration, DELETE this test and note it.
        out = lintc.template_render(
            '{{ for k, v in d }}{{ k }}={{ v }};{{ end }}',
            {"d": {"a": 1, "b": 2}},
        )
        self.assertIn("a=1;", out)
        self.assertIn("b=2;", out)


class TestScopeAwareFilterArgs(unittest.TestCase):
    def test_limit_arg_resolves_from_scope(self):
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit page.count }}{{ x }}{{ end }}',
                {"xs": ["a", "b", "c", "d"], "page": {"count": 2}},
            ),
            "ab",
        )

    def test_quoted_string_arg_still_literal(self):
        # Regression guard: scope-aware parsing must not break the date filter.
        self.assertEqual(
            lintc.template_render(
                '{{ d | date "%Y-%m-%d" }}',
                {"d": datetime.date(2026, 5, 28)},
            ),
            "2026-05-28",
        )

    def test_bare_identifier_without_scope_match_falls_back_to_string(self):
        # 'fallback' is not in scope; default should treat it as a string.
        self.assertEqual(
            lintc.template_render(
                '{{ x | default fallback }}',
                {"x": None},
            ),
            "fallback",
        )

    def test_default_arg_resolves_from_scope_when_path_exists(self):
        self.assertEqual(
            lintc.template_render(
                '{{ x | default page.fallback_title }}',
                {"x": None, "page": {"fallback_title": "Untitled"}},
            ),
            "Untitled",
        )

    def test_numeric_arg_still_integer(self):
        self.assertEqual(
            lintc.template_render(
                '{{ s | truncate 3 }}',
                {"s": "abcdef"},
            ),
            "abc…",
        )

    def test_chained_filters_on_for_iterable_with_scope_arg(self):
        # Locks in multi-filter + scope-arg behavior on a for-loop iterable.
        self.assertEqual(
            lintc.template_render(
                '{{ for x in xs | limit page.many | limit 2 }}{{ x }}{{ end }}',
                {"xs": ["a", "b", "c", "d", "e"], "page": {"many": 4}},
            ),
            "ab",
        )


class TestLoops(unittest.TestCase):
    def test_simple_loop(self):
        tpl = "{{ for x in items }}<li>{{ x }}</li>{{ end }}"
        self.assertEqual(
            lintc.template_render(tpl, {"items": ["a", "b", "c"]}),
            "<li>a</li><li>b</li><li>c</li>",
        )

    def test_loop_with_index(self):
        tpl = "{{ for x, i in items }}<li>{{ i }}:{{ x }}</li>{{ end }}"
        self.assertEqual(
            lintc.template_render(tpl, {"items": ["a", "b"]}),
            "<li>0:a</li><li>1:b</li>",
        )

    def test_loop_with_dotted_collection(self):
        tpl = "{{ for tag in page.tags }}#{{ tag }} {{ end }}"
        self.assertEqual(
            lintc.template_render(tpl, {"page": {"tags": ["swift", "macos"]}}),
            "#swift #macos ",
        )

    def test_loop_over_dict_yields_key_value(self):
        tpl = "{{ for k, v in d }}{{ k }}={{ v }}|{{ end }}"
        out = lintc.template_render(tpl, {"d": {"a": 1, "b": 2}})
        # dict iteration order is insertion-ordered in Python 3.7+
        self.assertEqual(out, "a=1|b=2|")

    def test_empty_loop(self):
        tpl = "before {{ for x in items }}{{ x }}{{ end }} after"
        self.assertEqual(
            lintc.template_render(tpl, {"items": []}),
            "before  after",
        )

    def test_nested_loops(self):
        tpl = "{{ for row in rows }}[{{ for c in row }}{{ c }}{{ end }}]{{ end }}"
        self.assertEqual(
            lintc.template_render(tpl, {"rows": [["a", "b"], ["c", "d"]]}),
            "[ab][cd]",
        )

    def test_unmatched_for_raises(self):
        with self.assertRaises(lintc.TemplateError):
            lintc.template_render("{{ for x in y }}", {"y": []})

    def test_unmatched_end_raises(self):
        with self.assertRaises(lintc.TemplateError):
            lintc.template_render("{{ end }}", {})


class TestConditionals(unittest.TestCase):
    def test_simple_if_true(self):
        self.assertEqual(
            lintc.template_render("{{ if x }}yes{{ end }}", {"x": True}),
            "yes",
        )

    def test_simple_if_false(self):
        self.assertEqual(
            lintc.template_render("{{ if x }}yes{{ end }}", {"x": False}),
            "",
        )

    def test_if_else(self):
        self.assertEqual(
            lintc.template_render("{{ if x }}T{{ else }}F{{ end }}", {"x": False}),
            "F",
        )

    def test_truthy_nonempty_list(self):
        self.assertEqual(
            lintc.template_render("{{ if x }}has{{ end }}", {"x": [1]}),
            "has",
        )

    def test_truthy_empty_list(self):
        self.assertEqual(
            lintc.template_render("{{ if x }}has{{ end }}", {"x": []}),
            "",
        )

    def test_equality(self):
        self.assertEqual(
            lintc.template_render('{{ if x == "live" }}LIVE{{ end }}', {"x": "live"}),
            "LIVE",
        )

    def test_inequality(self):
        self.assertEqual(
            lintc.template_render('{{ if x != "wip" }}done{{ end }}', {"x": "live"}),
            "done",
        )

    def test_in_membership(self):
        self.assertEqual(
            lintc.template_render(
                '{{ if x in ["a", "b"] }}yes{{ end }}',
                {"x": "a"},
            ),
            "yes",
        )

    def test_not_operator(self):
        self.assertEqual(
            lintc.template_render("{{ if not x }}no{{ end }}", {"x": False}),
            "no",
        )

    def test_and_operator(self):
        scope = {"a": True, "b": True}
        self.assertEqual(
            lintc.template_render("{{ if a and b }}both{{ end }}", scope),
            "both",
        )

    def test_or_operator(self):
        scope = {"a": False, "b": True}
        self.assertEqual(
            lintc.template_render("{{ if a or b }}either{{ end }}", scope),
            "either",
        )

    def test_parens_grouping(self):
        scope = {"a": True, "b": False, "c": True}
        self.assertEqual(
            lintc.template_render(
                "{{ if a and (b or c) }}yes{{ end }}", scope
            ),
            "yes",
        )

    def test_short_circuit_or(self):
        # If 'a' is truthy, 'b' (missing) should NOT be evaluated.
        self.assertEqual(
            lintc.template_render("{{ if a or b }}yes{{ end }}", {"a": True}),
            "yes",
        )

    def test_nested_if(self):
        scope = {"a": True, "b": True}
        self.assertEqual(
            lintc.template_render(
                "{{ if a }}A{{ if b }}B{{ end }}{{ end }}", scope
            ),
            "AB",
        )


class TestPartials(unittest.TestCase):
    def _lookup(self, partials):
        def lookup(name):
            if name not in partials:
                raise lintc.TemplateError("partial `%s` not found" % name)
            return partials[name]
        return lookup

    def test_partial_no_scope_change(self):
        partials = {"head.html": "<title>{{ page.title }}</title>"}
        out = lintc.template_render(
            '{{ partial "head.html" }}',
            {"page": {"title": "Hi"}},
            partial_lookup=self._lookup(partials),
        )
        self.assertEqual(out, "<title>Hi</title>")

    def test_partial_with_nested_object(self):
        partials = {"card.html": "<h3>{{ product.name }}</h3>"}
        out = lintc.template_render(
            '{{ partial "card.html" with product }}',
            {"product": {"name": "solcito"}},
            partial_lookup=self._lookup(partials),
        )
        self.assertEqual(out, "<h3>solcito</h3>")

    def test_partial_with_named_bindings(self):
        partials = {"link.html": '<a href="{{ url }}">{{ label }}</a>'}
        out = lintc.template_render(
            '{{ partial "link.html" with url=page.url label=page.title }}',
            {"page": {"url": "/x", "title": "X"}},
            partial_lookup=self._lookup(partials),
        )
        self.assertEqual(out, '<a href="/x">X</a>')

    def test_partial_sees_site_and_data(self):
        partials = {"foot.html": "© {{ site.year }}"}
        out = lintc.template_render(
            '{{ partial "foot.html" }}',
            {"site": {"year": 2026}},
            partial_lookup=self._lookup(partials),
        )
        self.assertEqual(out, "© 2026")

    def test_missing_partial_raises(self):
        with self.assertRaises(lintc.TemplateError):
            lintc.template_render(
                '{{ partial "nope.html" }}',
                {},
                partial_lookup=self._lookup({}),
            )


class TestLayout(unittest.TestCase):
    def _lookup(self, partials):
        def lookup(name):
            if name not in partials:
                raise lintc.TemplateError("partial `%s` not found" % name)
            return partials[name]
        return lookup

    def test_layout_wraps_inner(self):
        partials = {"_base.html": "<html>{{ inner | raw }}</html>"}
        tpl = '{{ layout "_base.html" }}<h1>Hello</h1>'
        out = lintc.template_render(
            tpl,
            {},
            partial_lookup=self._lookup(partials),
        )
        self.assertEqual(out, "<html><h1>Hello</h1></html>")

    def test_layout_passes_page_scope(self):
        partials = {"_base.html": "<title>{{ page.title }}</title>{{ inner | raw }}"}
        tpl = '{{ layout "_base.html" }}<p>body of {{ page.title }}</p>'
        out = lintc.template_render(
            tpl,
            {"page": {"title": "Hi"}},
            partial_lookup=self._lookup(partials),
        )
        self.assertEqual(out, "<title>Hi</title><p>body of Hi</p>")


class TestLintcVersionScopeVar(unittest.TestCase):
    """v0.2.1: render_page exposes lintc.version as a template var."""

    def test_lintc_version_in_scope(self):
        """{{ lintc.version }} renders to the running lintc version string."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "content" / "pages").mkdir(parents=True)
            (root / "src" / "layouts").mkdir(parents=True)
            (root / "src" / "data").mkdir(parents=True)
            # Minimal site.yaml + nav.yaml so load_config has data to read.
            (root / "src" / "data" / "site.yaml").write_text("author: Test\n")
            # Minimal page + layout that interpolates {{ lintc.version }}.
            (root / "src" / "content" / "pages" / "home.yaml").write_text(
                "title: Home\nslug: home\ndescription: Test page\n"
            )
            (root / "src" / "layouts" / "home.html").write_text(
                "<html><body>built with lintc {{ lintc.version }}</body></html>"
            )
            cfg = lintc.load_config(root)
            pages = lintc.derive_pages(cfg, lintc.discover_pages(cfg))
            home = [p for p in pages if p.slug == "home"][0]
            html = lintc.render_page(cfg, home, pages)
            self.assertIn("built with lintc " + lintc.__version__, html,
                "expected {{ lintc.version }} to render the lintc version string")


if __name__ == "__main__":
    unittest.main()
