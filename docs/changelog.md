# Changelog

All notable changes to lintc are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0] — 2026-05-29

### Added

- **Bundled check-time plugin: `terminal-mock`.** Regenerates a product
  page's `terminal.body_html` block (the styled-HTML terminal mock) by
  capturing real CLI output: runs the configured binary under a PTY so
  the CLI emits its normal TTY-gated ANSI, converts the ANSI escape
  sequences to the site's `t-*` `<span>` classes, wraps the result in
  static shell chrome, and rewrites the `terminal.body_html` block
  scalar in the mapped YAML file. A body-content hash is committed to
  `src/data/lintc-terminal.lock` using the same drift/review flow as
  `remote-sync` and `tag-sync` — the YAML is mutated on disk during
  `lintc check` and changes are reviewed with `git diff`. Enable under
  `check.plugins.terminal-mock` with `{command, local}` mappings
  (optional `args` and `columns`, default 120). Non-destructive: leaves
  the file unchanged when the command is not found, exits non-zero, or
  produces no output.

## [0.8.0] — 2026-05-29

### Added

- **Bundled check-time plugin: `tag-sync`.** Sets a content YAML's
  `version:` field from a repo's latest git tag. Tags are fetched via
  `git ls-remote --tags`; the plugin picks the highest semver release
  tag (pre-release tags are skipped) and rewrites the top-level
  `version:` line in each mapped file. State is tracked in
  `src/data/lintc-tag.lock` using the same drift/review flow as
  `remote-sync` — the field is mutated on disk during `lintc check`
  and the diff is reviewed with `git diff`. Enable under
  `check.plugins.tag-sync` with `{repo, local}` mappings (optional
  `field`, default `version`). Non-destructive: leaves the field
  unchanged on fetch failure, when no tags are found, or when the
  target line is absent from the file.

## [0.7.0] — 2026-05-29

### Added

- **`lintc-swiper` loop mode.** The carousel shortcode now accepts a
  `loop` attribute — `{{< lintc-swiper loop="true" >}}` — which renders
  `data-loop="true"` on the root. In loop mode the slide index wraps past
  either end and the prev/next buttons never disable, so advancing past
  the last slide returns to the first (and vice-versa). Default behavior
  is unchanged: omit the attribute and the carousel stays bounded with
  disabled buttons at the ends.

## [0.6.0] — 2026-05-29

### Added

- **Build-time plugin mechanism.** Plugins are enabled via a new
  `build.plugins` mapping in `lintc.yaml`, keyed by plugin slug (e.g.
  `lintc-swiper: {}`). Plugin modules live in the `lintc_plugins`
  namespace package — lintc discovers them automatically (module
  filename with underscores→hyphens gives the slug) and registers each
  plugin's shortcode → partial mapping at startup; a slug listed under
  `build.plugins` that has no discovered module is a config error. A
  plugin module exposes module-level `SHORTCODE`, `PARTIAL`, and
  `ASSETS` attributes. On `build`, `serve`, and `check`, lintc emits
  each enabled plugin's asset files to `dist/assets/plugins/<slug>/`
  and injects the corresponding `<link>` and `<script defer>` tags into
  every page that uses the shortcode. Assets are emitted only for pages
  that actually use the plugin's shortcode — pages that don't use it
  are not affected.

- **Bundled plugin: `lintc-swiper`.** A from-scratch, zero-dependency
  inline image carousel authored via the `{{< lintc-swiper >}}`
  shortcode. Supports drag/swipe with momentum, prev/next arrow
  controls, dot pagination, and keyboard navigation. Ships as part of
  the lintc package (`lintc_plugins/`) and replaces any Embla-based
  carousel approach.

### Notes

- All additions are backwards-compatible; sites without `build.plugins`
  configured are unaffected.

## [0.5.0] — 2026-05-28

### Added

- **Global `sections` map in template scope.** Every page render (not
  just section-indexes) now has `sections` available — a dict keyed by
  section name, each value `{title, description, intro, children}`.
  Lets non-index pages iterate over another section's pages, e.g.
  surfacing latest blog posts on the home page or featured products in
  a sidebar. The existing `section` variable on section-indexes is
  unchanged. A section with an `_index.yaml` but no child pages appears
  with `children: []`.

- **`limit:N` filter for lists.** Returns the first `N` items of a
  list. Sits alongside `truncate` (which is string-only). Raises a
  template error for non-integer or negative arguments; tolerates
  `None` input (returns `[]`).

- **Filters apply to `for`-loop iterables.** `{{ for x in xs | limit
  2 }}` works — the loop header's iterable is evaluated through the
  same filter-aware path as `{{ var }}` interpolation. Previously
  for-loops resolved their iterable as a bare path and ignored any
  `|` filter. Plain, dotted-path, and `k, v` iteration are unchanged.

- **Scope-aware filter arguments.** An unquoted, identifier-shaped
  filter argument (e.g. `page.count`) is resolved against the current
  scope chain when such a path exists, otherwise treated as a literal
  string. Quoted strings, ints, and floats remain literal. Enables
  `{{ list | limit page.count }}` and `{{ x | default
  page.fallback_title }}`. Quote an argument to force a literal.

### Notes

- All additions are backwards-compatible; no existing template syntax
  changes.

## [0.4.2] — 2026-05-25

### Changed

- **Republish of 0.4.1 source under a new version.** Functionally
  identical to 0.4.1 (no code or behavior changes). The version bump
  exists so the corresponding 0.4.1 PyPI release can be deleted: the
  source git history was rewritten (see repo's project notes), making
  the 0.4.1 archive on PyPI reference commits that no longer exist
  upstream. 0.4.2 publishes from the current orphan trunk and becomes
  the canonical artifact going forward.

## [0.4.1] — 2026-05-25

### Fixed

- **Template engine: bracket-key access for dict values.** Templates can now
  use `{{ page.body_sections["Install"] | raw }}` and
  `{{ if page.body_sections["Why it exists"] }}...{{ end }}`. v0.4.0 added
  `page.body_sections` and the spec promised this syntax, but the template
  engine only supported dot-paths — bracket keys silently broke. Both
  `_tpl_resolve_path` and the condition tokenizer now understand
  `["string key"]` and `['string key']` segments (any character except the
  matching quote allowed inside, including spaces and dots). Pure templates
  using dot-syntax continue to work unchanged.

## [0.4.0] — 2026-05-25

### Added

- **`page.body_sections` template scope key.** When a page uses
  `body_source`, lintc additionally parses the rendered Markdown HTML into
  sections keyed by each `## h2` heading's text and exposes them as a
  dict (`page.body_sections["Heading Text"]`). Layouts can selectively
  render individual sections wrapped in their own custom templates, giving
  the layout structural control while keeping the README (or any synced
  Markdown) as the canonical content source. Content before the first h2 is
  discarded. Existing `page.body_html` (full rendered Markdown) is
  unchanged and continues to work; `body_sections` is purely additive. See
  docs/index.md → Accessing body sections individually.

## [0.3.1] — 2026-05-25

### Fixed

- **`run_check` now runs plugins BEFORE the temp build.** Previously
  plugins ran after the build, which meant plugins that write files
  (e.g., `remote-sync` writing `body_source` targets) couldn't make their
  output available to the build's `render_page`. First-time setup with
  `body_source` + `remote-sync` required a manual `curl` bootstrap.
  Now: plugins run, then build runs, so initial sync just works.

## [0.3.0] — 2026-05-25

### Added

- **`body_source` page field.** Any page (.yaml or .md frontmatter) can
  declare `body_source: <path>`. lintc reads the file at that path,
  renders it as Markdown, and exposes `{{ page.body_html | raw }}` to the
  layout. Lets sites embed free-form Markdown into structured pages
  without rewriting their schema.
- **Bundled `remote-sync` plugin.** Declares a mapping of `(remote URL,
  local path)`. On `lintc check`, fetches each remote, hashes it,
  compares to a committed lockfile (`src/data/lintc-sync.lock`), and
  writes the file + updates the lockfile if upstream changed. Surfaces
  drift via git working-tree state, not lintc exit code. Replaces the
  pattern of hardcoding upstream-derived content in pages.

### Changed (BREAKING)

- **Removed `portfolio-check` plugin.** The new `remote-sync` model
  doesn't need GitHub-repo-list parity — each remote-sync mapping is
  declared explicitly. Existing users with `check.plugins.portfolio-check`
  in `lintc.yaml` should remove that block and (if they want the
  underlying drift-prevention) add a `remote-sync` block with their
  per-repo URL mappings.
- **`lintc check` may now modify files in the working tree.** When
  `remote-sync` is configured and a remote has changed, the plugin
  writes the new content to the local path and updates the lockfile.
  Users should expect a possibly-dirty working tree after `check` runs.

### Removed

- `lintc_plugins.portfolio_check` module. `from lintc_plugins.portfolio_check
  import run` will fail with `ModuleNotFoundError`. No replacement function;
  the drift-detection responsibility moves to `remote-sync`.

## [0.2.1] — 2026-05-25

### Added

- `lintc.version` template variable. Site templates can render the lintc
  version that built them, e.g., `Built with lintc v{{ lintc.version }}`
  in a footer. Available in every layout/partial; no config required.

## [0.2.0] — 2026-05-25

### Added

- **`src/data/lintc.yaml`** — optional config file for `lintc check`. Sites
  customize stray markers, set an email allowlist, and enable plugins. See
  the Configuration section in `docs/index.md`.
- **Plugin mechanism** — modules in the `lintc_plugins/` namespace package
  (PEP 420) are discovered at runtime and run during `lintc check` iff their
  slug appears under `check.plugins` in `lintc.yaml`. Third-party PyPI
  plugins contribute to the same namespace and are discovered the same way.
  See the Plugins section in `docs/index.md`.
- **Bundled `portfolio-check` plugin** — the existing GitHub-repo parity
  check, extracted into a plugin and made configurable. Disabled by default;
  enable via `check.plugins.portfolio-check` with `owner` + optional
  `ignore` + optional `content_dirs`.

### Changed (BREAKING)

- The hardcoded `@lintuxt.ai` email check is removed. New users get no
  email check by default. Existing users who relied on the old check should
  add `email_allowlist: ["@your-domain"]` to `src/data/lintc.yaml`.
- The hardcoded GitHub-parity check is removed from `lintc.py`. The logic
  moves to the bundled `portfolio-check` plugin. Existing users who relied
  on it should enable the plugin in `lintc.yaml` with their `owner`,
  `ignore`, and `content_dirs` settings.
- `lintc.Config` now has a required `check` constructor argument. Anyone
  importing `Config` directly needs to pass it (use
  `lintc.load_config(root)` which handles this automatically).

### Removed

- Module-level constants in `lintc.py`: `GITHUB_OWNER`, `GITHUB_IGNORE`,
  `_STRAY_MARKERS`.
- Module-level functions in `lintc.py`: `_fetch_github_json`,
  `fetch_public_repos`, `missing_product_pages`. Equivalent logic is now in
  `lintc_plugins.portfolio_check`; if you imported these directly, switch
  to `from lintc_plugins.portfolio_check import run` (the public API; the
  private `_fetch_public_repos` helper is not exported).

## [0.1.3] — 2026-05-25

### Changed

- The `lintc check` GitHub-repo parity check now walks both
  `src/content/products/` and `src/content/engineering/` when looking
  for product pages. A public sibling repo satisfies the check if it
  has a page in either directory.
- `lintc` removed from the default `GITHUB_IGNORE` set: it now belongs
  on /engineering/ pages of sites using lintc, not in the exemption
  list. Site authors with their own ignore conventions can still
  customize.

## [0.1.2] — 2026-05-25

### Changed

- Refresh PyPI project metadata: the `pyproject.toml` description string no
  longer mentions "Hugo-conceptual". No code change; this release exists to
  push the updated description to PyPI (project description is captured at
  publish time and cannot be updated retroactively for an existing release).

## [0.1.1] — 2026-05-25

### Changed

- `GITHUB_IGNORE` now includes `lintc`. The `lintc check` parity check no
  longer flags the lintc repo itself as a "public repo missing a product
  page" when run from a sibling site. Matches the existing convention for
  `lintuxt` (the site repo) and `swift-cli-kit` (a shared library).

## [0.1.0] — 2026-05-24

### Initial release

Extracted from `lintuxt/lintuxt`, where it was developed and proven in
production at [lintuxt.ai](https://lintuxt.ai). Feature set at v0.1.0:

- **Build pipeline:** discover → parse → derive → render → emit, in a single
  pass. Generates static HTML, sitemap, and live-reload-aware dev server
  output under `dist/`.
- **Content model:** YAML structured pages (e.g. home, resume, product pages)
  + Markdown posts with YAML front matter (blog).
- **Layouts and partials:** layout inheritance with
  `{{ layout "name.html" }}` and reusable partials via
  `{{ partial "name.html" }}`. Layout selection follows section/slug/explicit
  rules.
- **Template engine:** mustache-style `{{ var }}` interpolation with `| raw`
  bypass, `{{ for x in list }}…{{ end }}` loops, `{{ if cond }}…{{ else }}…{{ end }}`
  conditionals with `==`/`and`/`or`/`not`, named filters
  (`raw`, `lower`, `default`, `date`, `join`), and lintc-style comments
  `{{# … #}}`.
- **Markdown subset:** paragraphs, headings, lists, code blocks, blockquotes,
  horizontal rules, inline emphasis/links/code, fenced code with language
  hints, raw HTML block passthrough (CommonMark §4.6), and shortcodes
  (`{{< name attr="value" >}}…{{< /name >}}`).
- **YAML subset:** block mappings/sequences, flow forms, block scalars
  (`|`, `>`, `|-`, `>-`), quote-aware comment stripping, and
  preservation of `#` inside block-scalar content (per YAML 1.2).
- **Dev server:** `lintc serve` runs an HTTP server with mtime-polling file
  watcher and Server-Sent Events live-reload. Client-disconnect tracebacks
  are silenced cleanly.
- **Validation:** `lintc check` runs post-emit link/asset validation +
  GitHub-repo product-page parity. Same validations also run as part of
  `lintc build`.
- **Error overlay:** SSE-driven browser overlay shows YAML/template/build
  errors with file/line/snippet during `lintc serve`.

[0.4.2]: https://github.com/lintuxt/lintc/releases/tag/v0.4.2
[0.4.1]: https://github.com/lintuxt/lintc/releases/tag/v0.4.1
[0.4.0]: https://github.com/lintuxt/lintc/releases/tag/v0.4.0
[0.3.1]: https://github.com/lintuxt/lintc/releases/tag/v0.3.1
[0.3.0]: https://github.com/lintuxt/lintc/releases/tag/v0.3.0
[0.2.1]: https://github.com/lintuxt/lintc/releases/tag/v0.2.1
[0.2.0]: https://github.com/lintuxt/lintc/releases/tag/v0.2.0
[0.1.3]: https://github.com/lintuxt/lintc/releases/tag/v0.1.3
[0.1.2]: https://github.com/lintuxt/lintc/releases/tag/v0.1.2
[0.1.1]: https://github.com/lintuxt/lintc/releases/tag/v0.1.1
[0.1.0]: https://github.com/lintuxt/lintc/releases/tag/v0.1.0
