# lintc

`lintc` is a single-file Python static-site generator. It compiles a base
layout + partials + Markdown content + YAML data + shortcodes into a static
`dist/` — implemented in Python stdlib only, with no pip dependencies, no
Node, no build tools beyond Python itself.

It is designed for personal sites, project pages, and small documentation
sites where you want the templating power of a real SSG without the install
footprint. The whole compiler is one file (`lintc.py`).

## Commands

### `lintc build` — production build

```sh
lintc build
```

Rebuilds the site from `src/` into `dist/`. Drafts excluded. Any error
exits non-zero.

Flags:

- `--root DIR` — build a different directory (default: current directory).
- `--include-drafts` — include `draft: true` content in production output.

### `lintc serve` — dev server

```sh
lintc serve
```

Builds to `dist/` and serves `http://127.0.0.1:8000/`. Watches `src/`;
each change triggers a rebuild and a live-reload broadcast to connected
browsers. Errors render as an in-browser overlay; the server keeps
running.

Flags:

- `--root DIR`, `--host HOST`, `--port PORT` — standard.
- `--no-reload` — skip the live-reload script injection (rarely useful).
- `--no-drafts` — hide drafts (default in serve is to show them).

### `lintc check` — pre-deploy verification

```sh
lintc check
```

Builds to a temp directory and runs validators:

1. **Broken internal links** — every `href`/`src` resolves to a real
   emitted file. Always on; no config.
2. **Stray markers** — no `TODO` / `FIXME` / `PLACEHOLDER` /
   `lorem ipsum` (or your custom list) in any emitted file. Defaults
   are on; configure or disable via `check.stray_markers` in
   `src/data/lintc.yaml`.
3. **Email allowlist** — emails in emitted files must match a pattern
   in `check.email_allowlist`. Off unless configured.
4. **Plugins** — every plugin enabled under `check.plugins` runs.
   See the **Plugins** section for available plugins (bundled and
   third-party) and how to write your own.

**Note:** if plugins are configured (e.g., `remote-sync`), `lintc check` may
modify files in the working tree. Review changes with `git diff` before
committing — the plugin's behavior is documented per-plugin.

Exit code 0 = all passed, 1 = any failure. Useful as a git pre-push hook.
See **Configuration** below for the full config schema.

## Configuration

`lintc` reads optional config from `src/data/lintc.yaml`. Without this file,
`lintc check` runs sensible defaults: broken-link check on, stray-marker
check on with built-in markers, no email check, no plugins.

### Full schema

```yaml
check:
  email_allowlist:                  # list[str] | null. Default: null (no check)
    - "@your-domain.com"

  stray_markers:                    # list[str]. Default: ["TODO", "FIXME", "PLACEHOLDER", "lorem ipsum"]
    - "TODO"                        # set to [] to disable

  plugins:                          # dict[slug → dict] | null. Default: null
    remote-sync:                    # presence enables the plugin
      mappings:                     # plugin-specific config
        - remote: https://example.com/README.md
          local: src/synced/example.md
```

### Field reference

| Field | Type | When missing or null | When empty list |
|---|---|---|---|
| `check.email_allowlist` | `list[str]` | OFF | OFF |
| `check.stray_markers` | `list[str]` | use built-in defaults | OFF |
| `check.plugins` | `dict` | no plugins run | no plugins run |
| `check.plugins.<slug>` | `dict` | plugin disabled | enabled with empty config |

### Common configurations

**Blog with no checks** — omit `src/data/lintc.yaml` entirely. Stray-marker
check runs with built-in defaults; nothing else.

**Personal site with email allowlist**:

```yaml
check:
  email_allowlist: ["@your-domain.com"]
```

**Site that mirrors upstream READMEs into pages**:

```yaml
check:
  email_allowlist: ["@your-domain.com"]
  plugins:
    remote-sync:
      mappings:
        - remote: https://raw.githubusercontent.com/your-org/proj-a/main/README.md
          local: src/synced/proj-a.md
        - remote: https://raw.githubusercontent.com/your-org/proj-b/main/README.md
          local: src/synced/proj-b.md
```

Pair this with the `body_source` page field (see Pages section) to embed
the synced Markdown into each page's body.

**Site opting out of stray-marker defaults** (e.g. a dev-focused site
that legitimately has "TODO" in code samples):

```yaml
check:
  stray_markers: []                 # explicitly empty disables the check
```

### Behavior across CLI modes

| Validator | `lintc build` | `lintc serve` | `lintc check` |
|---|---|---|---|
| Broken internal links | error | error | error |
| Stray markers | error | warning | error |
| Email allowlist | error | warning | error |
| Plugins | not run | not run | error per plugin |

`serve` downgrades configurable validators to warnings so you can iterate
without the dev server constantly yelling. `build` and `check` treat them
as errors. Plugins are check-only because they can be slow or network-bound.

## Plugins

Plugins extend `lintc check` with additional validators. They run only in
`lintc check` (not `build` or `serve`), and only when explicitly enabled in
`src/data/lintc.yaml`.

### Enabling a plugin

Add the plugin's slug as a key under `check.plugins` in `lintc.yaml`. The
value is a dict of plugin-specific configuration:

```yaml
check:
  plugins:
    remote-sync:                    # plugin slug
      mappings:                     # plugin config
        - remote: https://example.com/README.md
          local: src/synced/example.md
```

Presence enables the plugin. Remove the key to disable it. There's no
separate `enabled: [...]` list.

### Bundled plugins

#### `remote-sync`

Mirrors external files to local paths via a committed lockfile. On
`lintc check`, fetches each declared remote, hashes it, compares against
`src/data/lintc-sync.lock`, and writes file + updates lockfile if upstream
changed. Surfaces drift via git working-tree state, not lintc exit code.

**This plugin mutates disk during `lintc check`** — when a remote has
changed, the plugin overwrites the local file and updates the lockfile.
Review changes with `git diff` before committing.

Config:

```yaml
check:
  plugins:
    remote-sync:
      mappings:
        - remote: https://raw.githubusercontent.com/owner/repo/main/README.md
          local: src/synced/repo.md
        - remote: https://raw.githubusercontent.com/owner/another/main/README.md
          local: src/synced/another.md
```

Behavior:

| Condition | Outcome |
|---|---|
| Lockfile entry missing | Write local, create lockfile entry, warn ("initial sync of...") |
| Lockfile sha matches fetched | Silent pass; no file writes |
| Lockfile sha differs | Overwrite local, update lockfile, warn ("synced ... upstream changed") |
| Network failure for one mapping | Warning, skip that mapping; other mappings proceed |

Common workflow:

1. Add a new mapping to `check.plugins.remote-sync.mappings` in `lintc.yaml`.
2. Run `lintc check` locally (or push and let the pre-push hook run it).
3. Plugin fetches, writes the file + lockfile entry, emits "initial sync" warning.
4. Review the synced file with `git diff`.
5. Commit the synced file + lockfile.
6. On every subsequent push, plugin re-fetches. If upstream changed, the file is updated + lockfile bumped; working tree dirty, push fails, you review + commit.

#### `tag-sync`

Sets a content YAML's `version:` field from a repo's latest git tag. On
`lintc check`, fetches tags via `git ls-remote --tags`, picks the highest
semver release tag (pre-release tags are skipped), and rewrites the
top-level `version:` line in each mapped file. State is tracked in
`src/data/lintc-tag.lock` using the same drift/review flow as
`remote-sync` — the field is mutated on disk during `lintc check` and
changes are reviewed with `git diff`.

**This plugin mutates disk during `lintc check`** — when the latest tag
differs from the lockfile, the plugin updates the `version:` field and
the lockfile. Review changes with `git diff` before committing.

Config:

```yaml
check:
  plugins:
    tag-sync:
      mappings:
        - repo: https://github.com/owner/repo.git
          local: src/content/products/repo.yaml
          # field: version   # optional; defaults to "version"
```

Behavior:

| Condition | Outcome |
|---|---|
| No tags found | Warning; field left unchanged |
| Fetch failure | Warning; field left unchanged |
| Target field absent from file | Warning; file left unchanged |
| Tag matches lockfile | Silent pass; no file writes |
| Tag differs from lockfile | Overwrite field, update lockfile, warn |

#### `terminal-mock`

Regenerates a product page's `terminal.body_html` block (the
styled-HTML terminal mock) by capturing real CLI output. On
`lintc check`, runs the configured binary under a PTY so the CLI emits
its normal TTY-gated ANSI, converts the ANSI escape sequences to the
site's `t-*` `<span>` classes, wraps the result in static shell chrome,
and rewrites the `terminal.body_html` block scalar in the mapped YAML
file. A body-content hash is committed to `src/data/lintc-terminal.lock`
using the same drift/review flow as `remote-sync` and `tag-sync` — the
YAML is mutated on disk during `lintc check` and changes are reviewed
with `git diff`.

**This plugin mutates disk during `lintc check`** — when the captured
output differs from the lockfile hash, the plugin overwrites the YAML
block and updates the lockfile. Review changes with `git diff` before
committing.

Config:

```yaml
check:
  plugins:
    terminal-mock:
      mappings:
        - command: displayswitcher
          local: src/content/products/displayswitcher.yaml
          # args: []        # optional; extra CLI arguments
          # columns: 120    # optional; terminal width (default: 120)
```

Behavior:

| Condition | Outcome |
|---|---|
| Command not found on PATH | Warning; file left unchanged |
| Command exits non-zero | Warning; file left unchanged |
| Command produces no output | Warning; file left unchanged |
| No `body_html:` block in YAML | Warning; file left unchanged |
| Hash matches lockfile | Silent pass; no file writes |
| Hash differs | Overwrite YAML block, update lockfile, warn |

Common workflow:

1. Add a mapping to `check.plugins.terminal-mock.mappings` in `lintc.yaml`.
2. Ensure the `command` is installed and on your PATH.
3. Run `lintc check` locally.
4. Plugin captures output, writes the updated YAML + lockfile, emits a
   regeneration warning.
5. Review changes with `git diff`.
6. Commit the updated YAML + lockfile.
7. On every subsequent push, plugin re-captures. If output changed, the
   YAML is updated + lockfile bumped; working tree dirty, you review +
   commit.

### Writing a plugin

Plugins live in the `lintc_plugins/` namespace package (PEP 420 — no
`__init__.py`). A plugin is a Python module exposing a `run` callable:

```python
# lintc_plugins/my_check.py
def run(cfg, plugin_config):
    """
    cfg: a lintc.Config instance (cfg.content_dir, cfg.site, cfg.data, cfg.dist available)
    plugin_config: dict from check.plugins.<slug> in lintc.yaml; {} if enabled with no config

    Returns: (errors: list[str], warnings: list[str])
    """
    errors = []
    warnings = []
    # ... your validation logic ...
    return errors, warnings
```

Naming convention: the file is `my_check.py` (snake_case); the slug in
`lintc.yaml` is `my-check` (kebab-case). lintc handles the translation.

### Plugin conventions

- **Prefix all error/warning messages with `<slug>:`** so multi-plugin output
  is attributable. Example: `"my-check: bad thing detected"`.
- **Treat network failures as warnings, not errors.** Catch transport errors
  (DNS, timeout, 5xx) and return them in the warnings list. Internet outages
  shouldn't fail `lintc check`.
- **Keep it self-contained.** Plugins should rely only on `cfg` + their own
  config dict. Importing other internal lintc functions makes future
  refactors fragile.

### Third-party plugins (future)

A plugin can ship as a separate PyPI package contributing to the
`lintc_plugins` namespace. Users install with `pip install lintc-<name>`,
add the slug to `check.plugins`, and the plugin is discovered automatically.
lintc itself doesn't need any change to support new plugins.

## Authoring

### Blog posts — `src/content/blog/<slug>.md`

Markdown body, YAML front matter:

```markdown
---
title: My post
description: One-sentence summary used in og:description and listings.
date: 2026-05-21
updated: 2026-05-25   # optional; overrides git-derived last-modified
tags: [ai, engineering]
draft: false
---

Body. Markdown subset. {{< callout >}}…{{< /callout >}} shortcodes work.
```

### Structured pages — `src/content/<section>/<slug>.yaml`

Pure YAML. Plain-text fields can contain raw inline HTML. URLs are
derived from the file path; the `pages/` segment is stripped from URLs
(so `src/content/pages/home.yaml` → `/`).

#### Embedding external Markdown — `body_source`

Any page (YAML or Markdown frontmatter) can declare a `body_source` field
pointing at a Markdown file. lintc reads that file, renders it as Markdown,
and exposes the rendered HTML to the layout as `{{ page.body_html | raw }}`.

```yaml
# src/content/products/solcito.yaml
title: solcito
slug: solcito
body_source: synced/solcito.md     # path relative to src/
features:
  - ...
```

```html
<!-- src/layouts/product.html -->
{{ if page.body_html }}
  <section class="prose">
    {{ page.body_html | raw }}
  </section>
{{ end }}
```

- Path is resolved relative to `src/` (the site root, not the page's directory).
- `body_source` pointing at a non-existent file is a hard error (build aborts).
- A page with both an inline Markdown body AND `body_source` is ambiguous → hard error. Pick one.
- Pairs well with the `remote-sync` plugin: declare a mapping
  `(<upstream URL> → src/synced/foo.md)`, point a page's `body_source` at that file. The page's body content stays in sync with upstream automatically.

#### Accessing body sections individually — `page.body_sections`

When `body_source` is set, lintc additionally parses the rendered Markdown
HTML into sections keyed by each `## h2` heading's text. Layouts access
them via `page.body_sections["Heading Text"]`:

```yaml
# src/content/products/solcito.yaml
body_source: synced/solcito.md
```

```markdown
<!-- synced/solcito.md -->
*Tagline.*

## Install
```sh
brew install solcito
```

## Why it exists
solcito is the inverse of...
```

```html
<!-- src/layouts/product.html -->
<section class="proj-section">
  <h2 class="section-title">Install in one line</h2>
  {{ page.body_sections["Install"] | raw }}
</section>

<section class="proj-section prose">
  <h2 class="section-title">Why it exists</h2>
  {{ page.body_sections["Why it exists"] | raw }}
</section>
```

Behavior:

- **Keys are the exact h2 text.** Case-sensitive. No normalization or
  slugification. What you write in `## Heading` is what the layout asks for.
- **Section values are the rendered HTML between this h2 and the next h2**
  (or end of document) — the h2 itself is NOT included. The layout supplies
  its own heading with its own phrasing.
- **Content before the first h2 is discarded.** If your README starts with
  a tagline + badges + an intro paragraph, none of that appears in
  `body_sections`. If you want it visible, wrap it in a `## Intro` (or any
  heading) at the top.
- **Sections not referenced by the layout are silently dropped.** The
  layout opts in to what it wants.
- **`page.body_html` (full rendered Markdown) is still populated.** Use it
  for whole-body rendering; use `body_sections` for surgical control. The
  two are independent.
- **Inline markup in headings is stripped from keys.** `## Install <code>tool</code>`
  becomes key `"Install tool"`.
- **Duplicate h2s: last-write-wins.** If your README has two `## Install`
  sections, the second one's body is the value at key `"Install"`.

### Section index — `src/content/<section>/_index.yaml`

Listing-page metadata. Optional. Children are auto-discovered from the
section's other files. Sort with `sort: "field"` (ascending) or
`sort: "-field"` (descending).

### Shared data — `src/data/*.yaml`

Available in templates as `data.<filename>`. `data/site.yaml` is special:
its top-level fields appear as `site.*`.

## Templates

Layouts live in `src/layouts/*.html`. The master layout is typically
`_base.html`; other layouts extend it with `{{ layout "_base.html" }}`.

Inside layouts:

- `{{ var }}` — escaped interpolation
- `{{ var | raw }}` — unescaped (use for HTML blobs and JSON-LD)
- `{{ var | lower }}` — string lowercase
- `{{ var | default "X" }}` — literal default
- `{{ var | date "%Y-%m-%d" }}` — date formatting
- `{{ var | join ", " }}` — list join
- `{{ var | limit 3 }}` — first N items of a list (also valid in a
  `for` iterable: `{{ for x in list | limit 3 }}`)
- `{{ if cond }}…{{ else }}…{{ end }}` — conditionals; `==`/`!=`/`and`/`or`/`not`
- `{{ for x in list }}…{{ end }}` — loops; the iterable may carry filters

A filter argument that is quoted, numeric, or a literal is used as-is.
An **unquoted, identifier-shaped** argument (e.g. `page.count`) is
resolved against the current scope when such a path exists, otherwise
treated as a literal string — so `{{ list | limit page.count }}` reads
the count from scope. Quote the argument to force a literal.
- `{{ partial "name.html" }}` — include a partial from `src/layouts/partials/`
- `{{# comment #}}` — emits nothing (use sparingly; lintc's tokenizer is
  line-based, so a comment on its own line can produce a blank line in
  output)

## Shortcodes

Create `src/layouts/partials/components/<name>.html`. Inside the
partial, `{{ inner | raw }}` is the inner content (for paired tags) and
`{{ <attr> }}` is each attribute from the opening tag, addressed by name.

Use it in any Markdown file:

```markdown
{{< name attr="value" >}}inner content{{< /name >}}
```

…or self-closing for components with no inner:

```markdown
{{< name attr="value" />}}
```

## Running the tests

If you've cloned the lintc repo and want to run the test suite:

```sh
uv run python tests/run_tests.py
```

Refresh the golden fixture after intentional template changes:

```sh
uv run python tests/update_goldens.py
```
