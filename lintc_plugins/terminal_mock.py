"""Terminal-mock — regenerate a product page's `terminal.body_html` from the
real CLI's output.

For each configured (command, local) mapping, runs the CLI under a PTY (so
CLIKit detects a TTY and emits its normal ANSI) with the hidden LINTUXT_DEBUG
fixture env set, converts the captured ANSI to the site's t-* span classes,
wraps it in the static shell chrome, and rewrites the `terminal.body_html`
block in the local YAML. Tracks a body hash in a committed lockfile so drift
surfaces via git working-tree state — review with `git diff` before
committing. Runs at `lintc check`, like remote-sync and tag-sync.

The CLI fixture scene is gated behind the hidden env var LINTUXT_DEBUG; it is
never a public flag and is undocumented. See the design spec.

Disabled by default. Enable via src/data/lintc.yaml:

    check:
      plugins:
        terminal-mock:
          mappings:
            - command: displayswitcher
              local: src/content/products/displayswitcher.yaml
            # optional per-mapping: args: []   columns: 120
"""
import fcntl
import html as _html
import os
import pty
import re
import shutil
import struct
import termios

# The hidden, undocumented fixture gate. Shared across the CLIKit family.
DEMO_ENV_VAR = "LINTUXT_DEBUG"
LOCKFILE_REL_PATH = "src/data/lintc-terminal.lock"

# SGR-code-set -> CSS class. Derived from swift-cli-kit Sources/CLIKit/Style.swift:
#   1 bold, 2 dim, 36 cyan, 90 gray, 96 brightCyan, 97 brightWhite, 35 magenta.
# Tone.title = bold+brightCyan; heading = bold; accent = brightCyan;
# value = brightWhite; muted = gray; subtle = dim; link = cyan; love = magenta.
_CLASS_BY_CODES = {
    frozenset({90}): "t-dim",
    frozenset({2}): "t-faint",
    frozenset({96}): "t-cyan",
    frozenset({1, 96}): "t-name",
    frozenset({1}): "t-name",
    frozenset({97}): "t-name",
    frozenset({36}): "t-link",
    frozenset({35}): "t-pink",
}

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def ansi_to_spans(text):
    """Convert a string of CLIKit ANSI output into t-* <span> HTML.

    Returns (html, warnings). Unknown code sets are emitted unwrapped and add
    a warning naming the offending code, so styling gaps fail loud.
    """
    out = []
    warnings = []
    active = set()
    pos = 0
    for m in _SGR_RE.finditer(text):
        _emit(out, warnings, text[pos:m.start()], active)
        pos = m.end()
        params = m.group(1)
        codes = [int(p) for p in params.split(";") if p != ""] or [0]
        for code in codes:
            if code == 0:
                active.clear()
            else:
                active.add(code)
    _emit(out, warnings, text[pos:], active)
    return "".join(out), warnings


def _emit(out, warnings, run, active):
    """Append one styled run of plain text to `out`, escaping HTML."""
    if run == "":
        return
    escaped = _html.escape(run, quote=False)
    if not active:
        out.append(escaped)
        return
    key = frozenset(active)
    cls = _CLASS_BY_CODES.get(key)
    if cls is None:
        warnings.append(
            "terminal-mock: no class for SGR code set %s — emitting unstyled"
            % sorted(key)
        )
        out.append(escaped)
        return
    out.append('<span class="%s">%s</span>' % (cls, escaped))
