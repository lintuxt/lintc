Zero-dependency Python static-site generator. Base layout + partials + Markdown content + YAML data + shortcodes. One file, stdlib only.

[![PyPI](https://img.shields.io/pypi/v/lintc.svg?v=2)](https://pypi.org/project/lintc/)
[![CI](https://github.com/lintuxt/lintc/actions/workflows/test.yml/badge.svg)](https://github.com/lintuxt/lintc/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/lintuxt/lintc/blob/main/LICENSE)

## Install

```sh
uv tool install lintc      # recommended — isolated, no env needed
pipx install lintc         # equivalent if you prefer pipx
pip install --user lintc   # also fine
```

Requires Python 3.9 or newer. No other dependencies.

## Quickstart

Scaffold a site:

```
src/
├── content/
│   ├── pages/home.yaml       # structured pages
│   ├── blog/*.md             # Markdown posts with YAML front matter
│   └── products/*.yaml
├── layouts/
│   ├── _base.html            # the master layout
│   ├── home.html             # page layouts
│   └── partials/             # shared chrome (head, header, footer, components)
├── data/                     # site-wide data (site.yaml, nav.yaml, etc.) + optional lintc.yaml
└── static/                   # copied verbatim into dist/
```

Build it:

```sh
lintc build              # emits dist/
lintc serve              # dev server with live reload at http://127.0.0.1:8000/
lintc check              # post-emit validations + configurable plugins
```

## CLI

```
lintc build [--root DIR] [--include-drafts]
lintc serve [--root DIR] [--host HOST] [--port PORT] [--no-reload] [--no-drafts]
lintc check [--root DIR]
lintc --version
lintc --help
```

`build` hides drafts by default — use `--include-drafts` to opt them in. `serve` shows drafts by default — use `--no-drafts` to hide them.

`lintc check`'s validators are configurable via `src/data/lintc.yaml` — see [the docs](https://github.com/lintuxt/lintc/blob/main/docs/index.md) for the schema.

## Why it exists

The reason lintc exists is that the static site for [lintuxt.ai](https://lintuxt.ai) needed a compiler, and the existing Python options either required a dependency graph I didn't want (Pelican, MkDocs) or a runtime I didn't want (Hugo's Go binary, Eleventy's Node.js). The constraint was: one file, stdlib only, no installation ceremony beyond having Python on the box.

It turned out to fit a useful niche. Personal sites and small documentation trees don't need the kitchen sink — they need layouts, partials, Markdown, structured data, and a dev server. lintc does exactly that and nothing more. The whole compiler is one Python file you can read top-to-bottom in an hour, including tests.

The trade-off is real: lintc is not Hugo, not Eleventy, not Astro. There's no plugin ecosystem of templates, no theme marketplace, no first-class image optimization, no markdown extension marketplace. If you're building a 500-page documentation site for a SaaS product, this is the wrong tool. If you're building a personal site, a project page, or a small handful of docs and you want the build pipeline to fit in your head, lintc is the right shape.

It also doubles as a portfolio surface: every release of lintc is visible on its own [engineering page on lintuxt.ai](https://lintuxt.ai/engineering/lintc/), embedded via lintc's own `body_source` field and the `remote-sync` plugin keeping the content in sync from this very README. The site you might be looking at is built by the thing you're reading about.

## Documentation

Full docs: [docs/index.md](https://github.com/lintuxt/lintc/blob/main/docs/index.md).
Changelog: [docs/changelog.md](https://github.com/lintuxt/lintc/blob/main/docs/changelog.md).

## License

MIT — see [LICENSE](https://github.com/lintuxt/lintc/blob/main/LICENSE).
