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


# Static shell chrome. The prompt/login/cursor lines are session decoration,
# not CLI output, so they live here (not captured). Timestamps are fixed so
# regeneration is byte-stable. Markup mirrors the hand-authored mock's classes.
_PROMPT = (
    '<span class="t-dim"># </span><span class="t-name">me</span>'
    '<span class="t-dim"> @ </span><span class="t-name">lintuxt.ai</span>'
    '<span class="t-dim"> in </span><span class="t-cyan">~</span>'
    '  <span class="t-faint">[%s]</span>'
)


def wrap_chrome(body_html, command):
    """Wrap captured CLI HTML in the static terminal-session chrome."""
    lines = [
        '<span class="t-dim">Last login: Sat May 23 11:30:55 on ttys009</span>',
        _PROMPT % "17:25:20",
        '<span class="t-dim">$ </span>' + command,
        "",
        body_html,
        "",
        _PROMPT % "17:25:31",
        '<span class="t-dim">$ </span>'
        '<span class="t-cursor" aria-hidden="true"></span>',
    ]
    return "\n".join(lines)


_BODY_KEY_RE = re.compile(r"^(?P<indent>\s*)body_html:\s*\|-?\s*$")


def _leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


def replace_body_html(text, body_lines):
    """Replace the content of the `body_html: |-` block scalar with
    `body_lines` (each re-indented to the block's content indent). Blank
    entries in `body_lines` become bare empty lines. Returns the new text, or
    None if there is no `body_html:` block.
    """
    lines = text.split("\n")
    key_idx = None
    key_indent = 0
    for i, line in enumerate(lines):
        m = _BODY_KEY_RE.match(line)
        if m:
            key_idx = i
            key_indent = len(m.group("indent"))
            break
    if key_idx is None:
        return None

    # Assumes 2-space YAML indentation (terminal: -> body_html: -> content).
    content_indent = key_indent + 2
    start = key_idx + 1
    # Scan the block: blank lines or lines indented >= content_indent.
    scan = start
    last_deep = start - 1  # last non-blank line belonging to the block
    while scan < len(lines):
        line = lines[scan]
        if line.strip() == "":
            scan += 1
            continue
        if _leading_spaces(line) >= content_indent:
            last_deep = scan
            scan += 1
            continue
        break  # dedented non-blank line: end of block

    pad = " " * content_indent
    rebuilt = [pad + bl if bl != "" else "" for bl in body_lines]
    # Replace [start, last_deep+1); keep trailing blanks (last_deep+1 .. scan).
    new_lines = lines[:start] + rebuilt + lines[last_deep + 1:]
    return "\n".join(new_lines)


def capture_under_pty(argv, env_extra, columns):
    """Run argv under a PTY; return (decoded_stdout, returncode).

    The child's stdout is a real terminal, so TTY-gated ANSI is emitted. A
    wide window size keeps table rows from wrapping. returncode is -1 if the
    child could not be spawned.
    """
    env = dict(os.environ)
    env.update(env_extra)

    pid, master_fd = pty.fork()
    if pid == 0:  # child
        try:
            _set_winsize(1, rows=200, cols=columns)
            os.execvpe(argv[0], argv, env)
        except Exception:
            os._exit(127)
    # parent
    chunks = []
    try:
        while True:
            try:
                data = os.read(master_fd, 65536)
            except OSError:  # EIO on slave close == EOF
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master_fd)
    _, status = os.waitpid(pid, 0)
    rc = os.waitstatus_to_exitcode(status)
    return b"".join(chunks).decode("utf-8", "replace"), rc


def _set_winsize(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


import hashlib


def run(cfg, plugin_config):
    """Regenerate each mapping's terminal.body_html from captured CLI output."""
    mappings = plugin_config.get("mappings")
    if mappings is None:
        return (["terminal-mock: `mappings` is required in plugin config"], [])
    if not isinstance(mappings, list):
        return (["terminal-mock: `mappings` must be a list of dicts"], [])
    if not mappings:
        return ([], [])

    errors, warnings = [], []
    lockfile_path = cfg.root / LOCKFILE_REL_PATH
    lock_data = _read_lockfile(lockfile_path)
    lock_modified = False

    for i, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append("terminal-mock: mappings[%d] must be a dict" % i)
            continue
        command = mapping.get("command")
        local = mapping.get("local")
        if not command or not local:
            errors.append(
                "terminal-mock: mappings[%d] missing `command` or `local`" % i)
            continue
        args = mapping.get("args", []) or []
        if not isinstance(args, list):
            errors.append(
                "terminal-mock: mappings[%d] `args` must be a list" % i)
            continue
        columns = mapping.get("columns", 120)

        if shutil.which(command) is None and not os.path.exists(command):
            warnings.append(
                "terminal-mock: command `%s` not found — leaving %s unchanged"
                % (command, local))
            continue

        local_full = cfg.root / local
        if not local_full.exists():
            warnings.append("terminal-mock: %s does not exist — skipping" % local)
            continue

        raw, rc = capture_under_pty(
            [command] + list(args), {DEMO_ENV_VAR: "1"}, columns)
        if rc != 0:
            warnings.append(
                "terminal-mock: `%s` exited %s — leaving %s unchanged"
                % (command, rc, local))
            continue
        if raw.strip() == "":
            warnings.append(
                "terminal-mock: `%s` produced no output — leaving %s unchanged"
                % (command, local))
            continue

        body_html, conv_warnings = ansi_to_spans(_normalize(raw))
        warnings.extend(conv_warnings)
        wrapped = wrap_chrome(body_html, command=os.path.basename(command))
        body_lines = wrapped.split("\n")

        text = local_full.read_text(encoding="utf-8")
        new_text = replace_body_html(text, body_lines)
        if new_text is None:
            warnings.append(
                "terminal-mock: %s has no `body_html:` block — skipping" % local)
            continue

        digest = hashlib.sha256(wrapped.encode("utf-8")).hexdigest()
        if new_text != text:
            local_full.write_text(new_text, encoding="utf-8")
            warnings.append(
                "terminal-mock: regenerated terminal mock in %s — review with "
                "`git diff` and commit" % local)
        if lock_data["entries"].get(local, {}).get("hash") != digest:
            lock_data["entries"][local] = {"command": command, "hash": digest}
            lock_modified = True

    if lock_modified:
        _write_lockfile(lockfile_path, lock_data)
    return errors, warnings


def _normalize(raw):
    """Strip a UTF-8 BOM and convert PTY CRLF line endings to LF."""
    return raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")


def _read_lockfile(path):
    if not path.exists():
        return {"version": 1, "entries": {}}
    import lintc
    try:
        data = lintc.yaml_parse(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "entries": {}}
    if not isinstance(data, dict):
        return {"version": 1, "entries": {}}
    if not isinstance(data.get("entries"), dict):
        data["entries"] = {}
    data.setdefault("version", 1)
    return data


def _write_lockfile(path, lock_data):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Auto-generated by the lintc terminal-mock plugin.",
        "# Commit this file. Do not edit manually.",
        "version: " + str(lock_data.get("version", 1)),
        "entries:",
    ]
    for local in sorted(lock_data["entries"].keys()):
        entry = lock_data["entries"][local]
        lines.append("  " + _quote(local) + ":")
        lines.append("    command: " + _quote(entry["command"]))
        lines.append("    hash: " + _quote(entry["hash"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
