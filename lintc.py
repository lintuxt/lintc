#!/usr/bin/env python3
"""lintc — the lintuxt compiler and dev server.

Python stdlib only. See docs/superpowers/specs/2026-05-23-lintc-compiler-design.md
for the full design. This file is organized by named comment blocks; functions
within a block are ordered helpers-first, entry-points-last.
"""

# --- imports ---
import argparse
import datetime
import difflib
import hashlib
import http.server
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


# --- constants ---
__version__ = "0.5.0"

# Defaults for src/data/lintc.yaml `check.stray_markers`.
# Used when the key is missing or null. Set to [] in lintc.yaml to disable.
DEFAULT_STRAY_MARKERS = ["TODO", "FIXME", "PLACEHOLDER", "lorem ipsum"]

TOOL_NAME = "lintc"
TOOL_VERSION = __version__


# --- yaml ---
class YamlError(Exception):
    """YAML parse error with file location info."""
    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


# Pre-compiled patterns for scalar recognition.
_YAML_INT = re.compile(r"^-?\d+$")
_YAML_FLOAT = re.compile(r"^-?\d+\.\d+$")
_YAML_BOOL = {"true": True, "false": False}
_YAML_NULL = {"null", "~", ""}


def _yaml_unescape_double(s):
    """Process \\n \\t \\\" \\\\ escapes inside a double-quoted scalar."""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "0": "\0"}
            out.append(mapping.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _yaml_parse_flow(text):
    """Parse a flow expression starting at text[0] = '[' or '{'. Returns (value, end_idx)."""
    i = 0
    if text[i] == "[":
        return _yaml_parse_flow_sequence(text, i)
    if text[i] == "{":
        return _yaml_parse_flow_mapping(text, i)
    raise YamlError("expected '[' or '{' for flow value")


def _yaml_read_flow_scalar(text, i):
    """Read a single scalar inside a flow context. Stops at , ] } (unquoted)."""
    if text[i] == '"':
        end = i + 1
        while end < len(text):
            if text[end] == "\\":
                end += 2
                continue
            if text[end] == '"':
                return _yaml_unescape_double(text[i + 1 : end]), end + 1
            end += 1
        raise YamlError("unterminated double-quoted string in flow")
    if text[i] == "'":
        end = i + 1
        while end < len(text):
            if text[end] == "'":
                if end + 1 < len(text) and text[end + 1] == "'":
                    end += 2
                    continue
                return text[i + 1 : end].replace("''", "'"), end + 1
            end += 1
        raise YamlError("unterminated single-quoted string in flow")
    end = i
    while end < len(text) and text[end] not in ",]}":
        end += 1
    raw = text[i:end].strip()
    return _yaml_parse_scalar(raw), end


def _yaml_parse_flow_at(text, i):
    """Parse a nested flow value starting at text[i]."""
    if text[i] == "[":
        return _yaml_parse_flow_sequence(text, i)
    if text[i] == "{":
        return _yaml_parse_flow_mapping(text, i)
    raise YamlError("internal: _yaml_parse_flow_at called on non-flow char")


def _yaml_parse_flow_sequence(text, i):
    assert text[i] == "["
    i += 1
    out = []
    while True:
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i >= len(text):
            raise YamlError("unterminated flow sequence")
        if text[i] == "]":
            return out, i + 1
        if text[i] in "[{":
            value, i = _yaml_parse_flow_at(text, i)
        else:
            value, i = _yaml_read_flow_scalar(text, i)
        out.append(value)
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i < len(text) and text[i] == ",":
            i += 1
        elif i < len(text) and text[i] == "]":
            return out, i + 1
        else:
            raise YamlError("expected ',' or ']' in flow sequence")


def _yaml_read_flow_key(text, i):
    """Read a mapping key inside a flow context. Stops at : , ] } (unquoted)."""
    if text[i] in '"\'':
        return _yaml_read_flow_scalar(text, i)
    end = i
    while end < len(text) and text[end] not in ":,]}":
        end += 1
    raw = text[i:end].strip()
    return _yaml_parse_scalar(raw), end


def _yaml_parse_flow_mapping(text, i):
    assert text[i] == "{"
    i += 1
    out = {}
    while True:
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i >= len(text):
            raise YamlError("unterminated flow mapping")
        if text[i] == "}":
            return out, i + 1
        key, i = _yaml_read_flow_key(text, i)
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i >= len(text) or text[i] != ":":
            raise YamlError("expected ':' in flow mapping")
        i += 1
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i >= len(text):
            raise YamlError("unterminated flow mapping")
        if text[i] in "[{":
            value, i = _yaml_parse_flow_at(text, i)
        else:
            value, i = _yaml_read_flow_scalar(text, i)
        out[key] = value
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i < len(text) and text[i] == ",":
            i += 1
        elif i < len(text) and text[i] == "}":
            return out, i + 1
        else:
            raise YamlError("expected ',' or '}' in flow mapping")


def _yaml_parse_scalar(text):
    """Parse a single scalar value or a flow expression."""
    s = text.strip()
    if s == "":
        return None
    if s.startswith("[") or s.startswith("{"):
        value, end = _yaml_parse_flow(s)
        if s[end:].strip() != "":
            raise YamlError("unexpected text after flow expression: %r" % s[end:])
        return value
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return _yaml_unescape_double(s[1:-1])
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s.startswith('"') and (not s.endswith('"') or len(s) < 2):
        raise YamlError("unterminated double-quoted string")
    if s.startswith("'") and (not s.endswith("'") or len(s) < 2):
        raise YamlError("unterminated single-quoted string")
    if s in _YAML_NULL:
        return None
    if s in _YAML_BOOL:
        return _YAML_BOOL[s]
    if _YAML_INT.match(s):
        return int(s)
    if _YAML_FLOAT.match(s):
        return float(s)
    return s  # plain (unquoted) string


def _yaml_split_lines(text):
    """Return (line_num, indent, content, stripped, original_raw) tuples, dropping comments.

    Blank lines are preserved as (n, -1, "", "", "") so block scalars can find them.
    Existing call sites that use only the first three elements still work.
    Block-scalar readers use index [4] (original_raw) so # in block-scalar content
    is never mistakenly treated as a YAML comment.
    """
    out = []
    for n, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() == "":
            out.append((n, -1, "", "", raw))
            continue
        # Strip trailing comment, respecting quotes.
        in_single = False
        in_double = False
        stripped = raw
        for i, c in enumerate(raw):
            if c == "'" and not in_double:
                in_single = not in_single
            elif c == '"' and not in_single:
                in_double = not in_double
            elif c == "#" and not in_single and not in_double:
                if i == 0 or raw[i - 1] in " \t":
                    stripped = raw[:i].rstrip()
                    break
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        out.append((n, indent, stripped.lstrip(" "), stripped, raw))
    # Drop trailing blank-only lines.
    while out and out[-1][2] == "" and out[-1][1] == -1:
        out.pop()
    return out


def _yaml_split_key_value(content, line_num):
    """Return (key, value_text) from a 'key: value' line, with key unquoted."""
    # Find ': ' (colon-space) OR a line ending in just ':'.
    # We scan respecting quoted keys.
    if content.startswith('"'):
        end = content.find('"', 1)
        if end == -1:
            raise YamlError("unterminated quoted key", line=line_num)
        key = content[1:end]
        rest = content[end + 1 :].lstrip()
    elif content.startswith("'"):
        end = content.find("'", 1)
        if end == -1:
            raise YamlError("unterminated quoted key", line=line_num)
        key = content[1:end]
        rest = content[end + 1 :].lstrip()
    else:
        # Find the first ': ' or trailing ':'
        m = re.search(r":(?:\s|$)", content)
        if not m:
            raise YamlError("expected ':' in mapping entry", line=line_num)
        key = content[: m.start()].strip()
        rest = content[m.start() + 1 :].lstrip()
        return key, rest
    if not rest.startswith(":"):
        raise YamlError("expected ':' after quoted key", line=line_num)
    rest = rest[1:].lstrip()
    return key, rest


def _yaml_skip_blanks(lines, pos):
    """Advance pos past any blank-only line records."""
    while pos < len(lines) and lines[pos][1] == -1:
        pos += 1
    return pos


def _yaml_read_block_scalar(lines, pos, indicator, base_indent):
    """Read a block scalar started by '|' or '>' marker on the parent line.

    `pos` should point to the first content line (indented more than base_indent).
    `indicator` is '|' (literal — preserve newlines) or '>' (folded — join lines).
    Returns (text, new_pos).
    """
    body_lines = []
    body_indent = None
    while pos < len(lines):
        n, indent, content, _stripped, original_raw = lines[pos]
        if indent == -1:
            # Blank line — only include if we've started the body and we'll keep going.
            body_lines.append("")
            pos += 1
            continue
        if body_indent is None:
            if indent <= base_indent:
                break
            body_indent = indent
        elif indent < body_indent:
            break
        body_lines.append(original_raw[body_indent:] if original_raw else "")
        pos += 1
    # Drop trailing blank lines (block scalars never end on a blank).
    while body_lines and body_lines[-1] == "":
        body_lines.pop()
    if indicator == "|":
        text = "\n".join(body_lines) + "\n"
    else:
        # Folded: walk body_lines, collapsing runs of non-blank into space-joined;
        # a blank line produces a newline paragraph break (not an extra blank line).
        result = ""
        buf = []
        for ln in body_lines:
            if ln == "":
                if buf:
                    result += " ".join(buf) + "\n"
                    buf = []
            else:
                buf.append(ln)
        if buf:
            result += " ".join(buf) + "\n"
        text = result
    return text, pos


def _yaml_parse_block(lines, pos, base_indent):
    """Parse a block-level value starting at lines[pos], indented at base_indent."""
    if pos >= len(lines):
        return None, pos
    pos = _yaml_skip_blanks(lines, pos)
    if pos >= len(lines):
        return None, pos
    n, indent, content = lines[pos][:3]
    if indent < base_indent:
        return None, pos
    if content.startswith("- "):
        return _yaml_parse_block_sequence(lines, pos, indent)
    if ":" in content:
        return _yaml_parse_block_mapping(lines, pos, indent)
    raise YamlError("unrecognized YAML at this position", line=n)


def _yaml_parse_block_sequence(lines, pos, base_indent):
    """Parse a contiguous block sequence (- item) at the given indent."""
    out = []
    while True:
        pos = _yaml_skip_blanks(lines, pos)
        if pos >= len(lines):
            break
        n, indent, content = lines[pos][:3]
        if indent < base_indent:
            break
        if indent > base_indent:
            raise YamlError("unexpected indent inside sequence", line=n, col=indent + 1)
        if not content.startswith("- "):
            break
        item_text = content[2:]
        if item_text.startswith("{") or item_text.startswith("["):
            out.append(_yaml_parse_scalar(item_text))
            pos += 1
            continue
        if item_text.startswith("- "):
            sub_lines = [(n, indent + 2, item_text, "", "")]
            inner_pos = pos + 1
            while inner_pos < len(lines):
                ii = lines[inner_pos][1]
                if ii != -1 and ii <= base_indent:
                    break
                sub_lines.append(lines[inner_pos])
                inner_pos += 1
            value, _ = _yaml_parse_block(sub_lines, 0, indent + 2)
            out.append(value)
            pos = inner_pos
            continue
        if re.search(r":(?:\s|$)", item_text) and not item_text.startswith('"') and not item_text.startswith("'"):
            sub_lines = [(n, indent + 2, item_text, "", "")]
            inner_pos = pos + 1
            while inner_pos < len(lines):
                ii = lines[inner_pos][1]
                if ii != -1 and ii <= base_indent:
                    break
                sub_lines.append(lines[inner_pos])
                inner_pos += 1
            value, _ = _yaml_parse_block_mapping(sub_lines, 0, indent + 2)
            out.append(value)
            pos = inner_pos
            continue
        out.append(_yaml_parse_scalar(item_text))
        pos += 1
    return out, pos


def _yaml_parse_block_mapping(lines, pos, base_indent):
    """Parse a contiguous block mapping at the given indent."""
    out = {}
    while True:
        pos = _yaml_skip_blanks(lines, pos)
        if pos >= len(lines):
            break
        n, indent, content = lines[pos][:3]
        if indent < base_indent:
            break
        if indent > base_indent:
            raise YamlError("unexpected indent inside mapping", line=n, col=indent + 1)
        key, value_text = _yaml_split_key_value(content, n)
        pos += 1
        stripped_value = value_text.strip()
        # `+` (keep all trailing newlines) is not implemented; reject to avoid
        # silently falling through to clip behavior.
        _block_scalar_m = re.match(r'^([|>])(-?)$', stripped_value)
        if _block_scalar_m:
            indicator = _block_scalar_m.group(1)
            chomping = _block_scalar_m.group(2)  # "" clip (one trailing \n), "-" strip
            pos = _yaml_skip_blanks(lines, pos)
            if pos >= len(lines) or lines[pos][1] <= base_indent:
                out[key] = ""
            else:
                text, pos = _yaml_read_block_scalar(lines, pos, indicator, base_indent)
                if chomping == "-":
                    text = text.rstrip("\n")
                out[key] = text
            continue
        if value_text:
            out[key] = _yaml_parse_scalar(value_text)
        else:
            pos = _yaml_skip_blanks(lines, pos)
            if pos >= len(lines) or lines[pos][1] <= base_indent:
                out[key] = None
            else:
                out[key], pos = _yaml_parse_block(lines, pos, lines[pos][1])
    return out, pos


def yaml_parse(text):
    """Parse a YAML subset document. Returns the parsed value or None for empty input."""
    if text is None or text.strip() == "":
        return None
    lines = _yaml_split_lines(text)
    if not lines:
        return None
    first = _yaml_skip_blanks(lines, 0)
    if first >= len(lines):
        return None
    first_content = lines[first][2]
    is_flow = first_content.startswith("[") or first_content.startswith("{")
    if len(lines) - first == 1 and (":" not in first_content or is_flow):
        return _yaml_parse_scalar(first_content)
    value, pos = _yaml_parse_block(lines, first, lines[first][1])
    return value


# --- markdown ---

# Regex: {{< name [attrs] >}}, {{< name [attrs] />}} (self-closing), {{< /name >}}
_SC_OPEN = re.compile(r"\{\{<\s*([a-zA-Z][\w-]*)\s*((?:\s+[\w-]+=\"[^\"]*\")*)\s*(/?)>\}\}")
_SC_CLOSE = re.compile(r"\{\{<\s*/\s*([a-zA-Z][\w-]*)\s*>\}\}")
_SC_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')


def _md_parse_attrs(attr_string):
    return {m.group(1): m.group(2) for m in _SC_ATTR.finditer(attr_string or "")}


def _md_encode_shortcode(invocations, name, context, attrs, inner):
    """Append a shortcode invocation; return its sentinel.

    Sentinel format: \\x00SC<id>\\x00
    All data lives in the invocations list; the sentinel is just an id token.
    This avoids embedding inner_html (which may itself contain \\x00 sentinels)
    inside the sentinel string, which would break the sentinel regex.
    """
    invocations.append({
        "name": name,
        "context": context,
        "attrs": attrs,
        "inner": inner,
    })
    return "\x00SC%d\x00" % (len(invocations) - 1)


def _html_escape(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _md_split_blocks(text):
    """Split into blocks, respecting fenced code blocks (which can contain blanks)."""
    blocks = []
    current = []
    in_fence = False
    for line in text.splitlines():
        m = re.match(r"^```(.*)$", line)
        if m and not in_fence:
            if current:
                blocks.append(current)
                current = []
            in_fence = True
            current.append(line)
            continue
        if in_fence:
            current.append(line)
            if line.startswith("```"):
                in_fence = False
                blocks.append(current)
                current = []
            continue
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _md_render_inline(text, invocations=None):
    """Render inline Markdown. Also extracts inline-context shortcodes into invocations."""
    if invocations is None:
        invocations = []
    placeholders = []

    # Extract paired inline shortcodes ({{< name >}}...{{< /name >}}) within a line.
    def _stash_paired_sc(m):
        name = m.group(1)
        attrs = _md_parse_attrs(m.group(2))
        inner_raw = m.group(3)
        inner_html = _md_render_inline(inner_raw, invocations)
        sentinel = _md_encode_shortcode(invocations, name, "inline", attrs, inner_html)
        placeholders.append(sentinel)
        return "\x00C%d\x00" % (len(placeholders) - 1)

    text = re.sub(
        r"\{\{<\s*([a-zA-Z][\w-]*)\s*((?:\s+[\w-]+=\"[^\"]*\")*)\s*>\}\}(.*?)\{\{<\s*/\s*\1\s*>\}\}",
        _stash_paired_sc,
        text,
        flags=re.DOTALL,
    )

    # Extract self-closing inline shortcodes ({{< name />}}).
    def _stash_self_sc(m):
        name = m.group(1)
        attrs = _md_parse_attrs(m.group(2))
        sentinel = _md_encode_shortcode(invocations, name, "inline", attrs, "")
        placeholders.append(sentinel)
        return "\x00C%d\x00" % (len(placeholders) - 1)

    text = re.sub(
        r"\{\{<\s*([a-zA-Z][\w-]*)\s*((?:\s+[\w-]+=\"[^\"]*\")*)\s*/>\}\}",
        _stash_self_sc,
        text,
    )

    # Step 1: extract `code` spans, replace with placeholders.
    def _stash_code(m):
        placeholders.append("<code>%s</code>" % _html_escape(m.group(1)))
        return "\x00C%d\x00" % (len(placeholders) - 1)

    text = re.sub(r"`([^`]+)`", _stash_code, text)

    # Step 2: recognize HTML tags, stash them as passthrough placeholders.
    def _stash_html(m):
        placeholders.append(m.group(0))
        return "\x00C%d\x00" % (len(placeholders) - 1)

    # Match opening, closing, or self-closing HTML tags.
    text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s+[^<>]*?)?/?>", _stash_html, text)

    # Step 3: escape remaining < > & in plain text (placeholders already safe).
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Step 4: images BEFORE links (so ![alt](url) doesn't accidentally match link rule).
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic (single * not part of **)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)

    # Restore placeholders.
    def _restore(m):
        idx = int(m.group(1))
        return placeholders[idx]

    text = re.sub(r"\x00C(\d+)\x00", _restore, text)
    return text


_MD_UL_RE = re.compile(r"^(\s*)([-*])\s+(.+)$")
_MD_OL_RE = re.compile(r"^(\s*)(\d+)\.\s+(.+)$")


def _md_is_list_line(line):
    return bool(_MD_UL_RE.match(line) or _MD_OL_RE.match(line))


def _md_render_list(lines, base_indent=0, ordered=None, invocations=None):
    """Render a list block. `lines` are list-item lines (plus continuations).

    Returns (html, lines_consumed).
    """
    if invocations is None:
        invocations = []
    items = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m_ul = _MD_UL_RE.match(line)
        m_ol = _MD_OL_RE.match(line)
        m = m_ul or m_ol
        if not m:
            break
        indent = len(m.group(1))
        if indent < base_indent:
            break
        if indent > base_indent:
            # Sub-list — gather its lines and render recursively.
            sub_lines = []
            while i < len(lines):
                nxt = lines[i]
                m_nxt_ul = _MD_UL_RE.match(nxt)
                m_nxt_ol = _MD_OL_RE.match(nxt)
                m_nxt = m_nxt_ul or m_nxt_ol
                if m_nxt and len(m_nxt.group(1)) >= base_indent + 2:
                    sub_lines.append(nxt)
                    i += 1
                else:
                    break
            sub_html, _ = _md_render_list(sub_lines, base_indent=base_indent + 2, invocations=invocations)
            # Append sublist html into the previous item.
            if items:
                items[-1] += "\n" + sub_html
            else:
                # No parent — degenerate; treat as a list at this indent.
                items.append(sub_html)
            continue
        # This-level item
        kind = "ol" if m_ol else "ul"
        if ordered is None:
            ordered = (kind == "ol")
        item_text = m.group(3)
        items.append(_md_render_inline(item_text, invocations))
        i += 1
    tag = "ol" if ordered else "ul"

    def _wrap_li(it):
        if "\n" in it:
            return "<li>%s\n</li>" % it
        return "<li>%s</li>" % it

    html = "<%s>\n" % tag + "\n".join(_wrap_li(it) for it in items) + "\n</%s>" % tag
    return html, i


def _md_render_block(lines, invocations=None):
    """Render a single block of contiguous lines."""
    if invocations is None:
        invocations = []
    first = lines[0]
    # If the block is entirely a single shortcode sentinel, return it as-is.
    if len(lines) == 1 and first.startswith("\x00SC") and first.endswith("\x00"):
        return first
    # Fenced code
    m_fence = re.match(r"^```(\S*)\s*$", first)
    if m_fence:
        lang = m_fence.group(1)
        # Body is everything between the fence lines (last line is closing fence).
        body_lines = lines[1:-1] if len(lines) >= 2 and lines[-1].startswith("```") else lines[1:]
        body = "\n".join(body_lines)
        body = _html_escape(body) + "\n"
        if lang:
            return '<pre><code class="language-%s">%s</code></pre>' % (lang, body)
        return "<pre><code>%s</code></pre>" % body
    # Horizontal rule
    if first.strip() == "---" and len(lines) == 1:
        return "<hr>"
    # Blockquote
    if first.startswith("> "):
        body = "\n".join(line[2:] if line.startswith("> ") else line for line in lines)
        return "<blockquote>%s</blockquote>" % _md_render_inline(body, invocations)
    # Heading
    m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", first)
    if m and len(lines) == 1:
        level = len(m.group(1))
        return "<h%d>%s</h%d>" % (level, _md_render_inline(m.group(2), invocations), level)
    # List
    if _md_is_list_line(first):
        html, _ = _md_render_list(lines, base_indent=0, invocations=invocations)
        return html
    # Raw HTML block (CommonMark §4.6 type 6) — pass through verbatim if the
    # first line begins with a block-level HTML tag. Detection is intentionally
    # narrow: opening tag must be one of the recognized block-level elements
    # and the block is emitted unmodified, including any nested inline HTML.
    if re.match(
        r"^\s*<(p|div|section|article|aside|figure|figcaption|table|thead|tbody|"
        r"tr|td|th|ul|ol|li|dl|dt|dd|blockquote|pre|h[1-6]|details|summary|"
        r"nav|header|footer|main|script|style|iframe|hr|br)\b",
        first,
        re.IGNORECASE,
    ):
        return "\n".join(lines)
    # Paragraph
    body = "\n".join(lines)
    return "<p>%s</p>" % _md_render_inline(body, invocations)


def _md_extract_block_shortcodes(text, invocations):
    """Find block-context shortcodes (open tag alone on a line, paired close alone too),
    render their inner as Markdown (recursively), and replace with sentinels."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m_open = _SC_OPEN.match(line.strip())
        # A "block context" requires the line to contain ONLY the open tag.
        if m_open and m_open.group(0).strip() == line.strip():
            name = m_open.group(1)
            attrs = _md_parse_attrs(m_open.group(2))
            self_closing = m_open.group(3) == "/"
            if self_closing:
                out.append(_md_encode_shortcode(invocations, name, "block", attrs, ""))
                i += 1
                continue
            # Find matching close on its own line.
            depth = 1
            inner = []
            j = i + 1
            while j < len(lines):
                inner_line = lines[j]
                m_close = _SC_CLOSE.match(inner_line.strip())
                if m_close and m_close.group(1) == name and m_close.group(0).strip() == inner_line.strip():
                    depth -= 1
                    if depth == 0:
                        break
                # Nested same-name shortcodes
                m_inner_open = _SC_OPEN.match(inner_line.strip())
                if (
                    m_inner_open
                    and m_inner_open.group(1) == name
                    and m_inner_open.group(3) != "/"
                    and m_inner_open.group(0).strip() == inner_line.strip()
                ):
                    depth += 1
                inner.append(inner_line)
                j += 1
            if j >= len(lines):
                # Unterminated — emit literally
                out.append(line)
                i += 1
                continue
            inner_html = markdown_render("\n".join(inner), _invocations=invocations)
            out.append(_md_encode_shortcode(invocations, name, "block", attrs, inner_html))
            i = j + 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def markdown_render(text, _invocations=None):
    """Render Markdown subset to HTML.

    `_invocations` (internal) collects shortcode invocations as
    {'name', 'context', 'attrs', 'inner'} dicts indexed by sentinel id.
    Callers needing to resolve sentinels pass an empty list and read it back.
    """
    if not text or text.strip() == "":
        return ""
    if _invocations is None:
        _invocations = []
    # Step 1: Extract block-context shortcodes (opening tag alone on a line).
    text = _md_extract_block_shortcodes(text, _invocations)
    # Step 2: Block-level rendering as before.
    blocks = _md_split_blocks(text)
    return "\n".join(_md_render_block(b, _invocations) for b in blocks)


# --- template ---


class TemplateError(Exception):
    """Template syntax / runtime error with location info."""
    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


def _suggest(needle, candidates):
    """Return ' (did you mean `X`?)' or empty string."""
    matches = difflib.get_close_matches(needle, list(candidates), n=1, cutoff=0.6)
    if matches:
        return " (did you mean `%s`?)" % matches[0]
    return ""


# Token kinds.
T_TEXT = "TEXT"
T_VAR = "VAR"           # {{ expr }}  (HTML-escaped)
T_COMMENT = "COMMENT"   # {{# ... #}}
T_PARTIAL = "PARTIAL"   # {{ partial ... }}
T_LAYOUT = "LAYOUT"     # {{ layout "name.html" }}
T_FOR = "FOR"           # {{ for x in coll }}
T_END = "END"           # {{ end }}
T_IF = "IF"             # {{ if expr }}
T_ELSE = "ELSE"         # {{ else }}

_TPL_TAG = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)
_TPL_COMMENT = re.compile(r"\{\{#\s*(.*?)\s*#\}\}", re.DOTALL)


def _tpl_tokenize(text):
    """Yield (kind, payload, position) tokens."""
    pos = 0
    while pos < len(text):
        # Comment is its own delimiter pair.
        m_comment = _TPL_COMMENT.search(text, pos)
        m_tag = _TPL_TAG.search(text, pos)
        # Pick the earlier match.
        if m_comment and (not m_tag or m_comment.start() <= m_tag.start()):
            if m_comment.start() > pos:
                yield (T_TEXT, text[pos : m_comment.start()], pos)
            yield (T_COMMENT, m_comment.group(1), m_comment.start())
            pos = m_comment.end()
            continue
        if not m_tag:
            yield (T_TEXT, text[pos:], pos)
            return
        if m_tag.start() > pos:
            yield (T_TEXT, text[pos : m_tag.start()], pos)
        payload = m_tag.group(1).strip()
        if payload.startswith("partial "):
            yield (T_PARTIAL, payload[len("partial ") :].strip(), m_tag.start())
        elif payload.startswith("layout "):
            yield (T_LAYOUT, payload[len("layout ") :].strip(), m_tag.start())
        elif payload.startswith("for "):
            yield (T_FOR, payload[len("for ") :].strip(), m_tag.start())
        elif payload == "end":
            yield (T_END, "", m_tag.start())
        elif payload.startswith("if "):
            yield (T_IF, payload[len("if ") :].strip(), m_tag.start())
        elif payload == "else":
            yield (T_ELSE, "", m_tag.start())
        else:
            yield (T_VAR, payload, m_tag.start())
        pos = m_tag.end()


def _tpl_split_path(path):
    """Split a template path into segments, supporting both dotted (`a.b.c`) and
    bracketed string keys (`a.b["c d"].e`). Returns a list of string keys.

    Bracket keys may use double or single quotes and may contain dots, spaces,
    and any character except the matching closing quote.
    """
    parts = []
    i = 0
    n = len(path)
    while i < n:
        ch = path[i]
        if ch == "[":
            if i + 1 >= n or path[i + 1] not in ('"', "'"):
                raise TemplateError(
                    "invalid path `%s`: expected quoted string after `[`" % path
                )
            quote = path[i + 1]
            close = path.find(quote + "]", i + 2)
            if close == -1:
                raise TemplateError(
                    "invalid path `%s`: unterminated bracketed key" % path
                )
            parts.append(path[i + 2:close])
            i = close + 2
        elif ch == ".":
            i += 1
        else:
            j = i
            while j < n and path[j] not in ".[":
                j += 1
            parts.append(path[i:j])
            i = j
    return parts


def _tpl_resolve_path(scope_chain, path):
    """Resolve `a.b.c` or `a.b["key"].c` against the scope chain (list of dicts, innermost first)."""
    parts = _tpl_split_path(path)
    if not parts:
        raise TemplateError("empty path: `%s`" % path)
    head = parts[0]
    rest = parts[1:]
    value = None
    found = False
    for scope in scope_chain:
        if isinstance(scope, dict) and head in scope:
            value = scope[head]
            found = True
            break
    if not found:
        all_names = set()
        for scope in scope_chain:
            if isinstance(scope, dict):
                all_names.update(scope.keys())
        raise TemplateError("undefined variable `%s`%s" % (path, _suggest(head, all_names)))
    walked = [head]
    for p in rest:
        if isinstance(value, dict) and p in value:
            value = value[p]
        elif hasattr(value, p):
            value = getattr(value, p)
        else:
            available = list(value.keys()) if isinstance(value, dict) else []
            raise TemplateError(
                "undefined attribute `%s` on `%s`%s"
                % (p, ".".join(walked), _suggest(p, available))
            )
        walked.append(p)
    return value


def _tpl_split_filter(f):
    """Split a filter expression 'name [arg]' into (name, raw_arg_or_None)."""
    m = re.match(r"^(\w+)(?:\s+(.*))?$", f.strip())
    if not m:
        raise TemplateError("invalid filter expression: `%s`" % f)
    return m.group(1), m.group(2)


def _tpl_parse_literal_arg(arg):
    """Parse a literal filter argument: \"string\", number, identifier."""
    arg = arg.strip()
    if arg.startswith('"') and arg.endswith('"'):
        return arg[1:-1]
    if arg.startswith("'") and arg.endswith("'"):
        return arg[1:-1]
    try:
        return int(arg)
    except ValueError:
        pass
    try:
        return float(arg)
    except ValueError:
        pass
    return arg  # bare identifier; treated as string


def _tpl_parse_filter_arg(arg, scope_chain):
    """Parse a filter argument with scope-path resolution.

    Quoted strings, ints, and floats are returned as literals (same as
    _tpl_parse_literal_arg). Identifier-shaped unquoted args are first
    looked up against the scope chain; if no such path exists, fall
    back to bare-string behavior.
    """
    s = arg.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if scope_chain is not None and re.match(r"^[A-Za-z_][\w.]*$", s):
        try:
            return _tpl_resolve_path(scope_chain, s)
        except TemplateError:
            pass
    return s


def _filter_upper(v, arg):
    return str(v).upper() if v is not None else ""


def _filter_lower(v, arg):
    return str(v).lower() if v is not None else ""


def _filter_length(v, arg):
    if v is None:
        return 0
    return len(v)


def _filter_join(v, arg):
    sep = arg if arg is not None else ""
    return sep.join(str(x) for x in (v or []))


def _filter_default(v, arg):
    return arg if v is None or v == "" else v


def _filter_date(v, arg):
    if v is None:
        return ""
    if isinstance(v, str):
        try:
            v = datetime.date.fromisoformat(v)
        except ValueError:
            return v
    fmt = arg or "%Y-%m-%d"
    return v.strftime(fmt)


def _filter_truncate(v, arg):
    n = int(arg) if arg is not None else 140
    s = str(v or "")
    if len(s) <= n:
        return s
    return s[:n] + "…"


def _filter_slug(v, arg):
    s = str(v or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _filter_markdown(v, arg):
    return markdown_render(str(v or ""))


def _filter_limit(v, arg):
    """List slicer: returns the first int(arg) items of v."""
    if v is None:
        return []
    try:
        n = int(arg)
    except (TypeError, ValueError):
        raise TemplateError("limit: argument must be an integer, got %r" % arg)
    if n < 0:
        raise TemplateError("limit: argument must be >= 0, got %d" % n)
    return list(v)[:n]


_TPL_FILTERS = {
    "upper": _filter_upper,
    "lower": _filter_lower,
    "length": _filter_length,
    "join": _filter_join,
    "default": _filter_default,
    "date": _filter_date,
    "truncate": _filter_truncate,
    "slug": _filter_slug,
    "markdown": _filter_markdown,
    "limit": _filter_limit,
}


def _tpl_apply_filters(value, filter_exprs, scope_chain=None):
    """Apply chained filters. Returns (value, raw_flag)."""
    raw = False
    for f in filter_exprs:
        name, arg = _tpl_split_filter(f)
        if name == "raw":
            raw = True
            continue
        if name not in _TPL_FILTERS:
            raise TemplateError(
                "unknown filter `%s`%s" % (name, _suggest(name, _TPL_FILTERS))
            )
        parsed_arg = _tpl_parse_filter_arg(arg, scope_chain) if arg else None
        value = _TPL_FILTERS[name](value, parsed_arg)
    return value, raw


def _tpl_eval_expr(expr, scope_chain):
    """Evaluate an expression like `page.title | raw` to (value, raw_flag)."""
    parts = [p.strip() for p in expr.split("|")]
    head = parts[0]
    filters = parts[1:]
    value = _tpl_resolve_path(scope_chain, head)
    return _tpl_apply_filters(value, filters, scope_chain)


def _tpl_truthy(v):
    if v is None or v is False or v == 0:
        return False
    if isinstance(v, (list, dict, str, tuple)) and len(v) == 0:
        return False
    return True


def _tpl_tokenize_cond(text):
    """Tokenize a condition expression into a flat list of (kind, value)."""
    tokens = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in " \t":
            i += 1
            continue
        if c == "(":
            tokens.append(("LP", "("))
            i += 1
            continue
        if c == ")":
            tokens.append(("RP", ")"))
            i += 1
            continue
        if c == "[":
            depth = 1
            j = i + 1
            while j < len(text) and depth:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                j += 1
            tokens.append(("LIST", text[i:j]))
            i = j
            continue
        if c == '"' or c == "'":
            j = i + 1
            while j < len(text) and text[j] != c:
                if text[j] == "\\":
                    j += 2
                else:
                    j += 1
            tokens.append(("STR", text[i + 1 : j]))
            i = j + 1
            continue
        if text[i:i + 2] == "==":
            tokens.append(("EQ", "=="))
            i += 2
            continue
        if text[i:i + 2] == "!=":
            tokens.append(("NE", "!="))
            i += 2
            continue
        m = re.match(r"-?\d+(?:\.\d+)?", text[i:])
        if m:
            tokens.append(("NUM", m.group(0)))
            i += len(m.group(0))
            continue
        m = re.match(r"[A-Za-z_][\w.]*", text[i:])
        if m:
            word = m.group(0)
            i += len(word)
            if word in ("and", "or", "not", "in", "true", "false", "null"):
                tokens.append((word.upper(), word))
                continue
            # Extend the path with any number of trailing ["key"] or ['key'] segments
            # so paths like page.body_sections["Why it exists"] tokenize as one PATH.
            while i < len(text) and text[i] == "[" and i + 1 < len(text) and text[i + 1] in ('"', "'"):
                quote = text[i + 1]
                close = text.find(quote + "]", i + 2)
                if close == -1:
                    raise TemplateError(
                        "unterminated bracketed key in path starting at `%s`" % word
                    )
                word += text[i:close + 2]
                i = close + 2
            tokens.append(("PATH", word))
            continue
        raise TemplateError("unexpected character in condition: `%s`" % c)
    return tokens


def _tpl_parse_literal_list(text):
    """Parse `[a, b, "c"]` literal. Returns a Python list of values."""
    body = text.strip()
    assert body.startswith("[") and body.endswith("]")
    body = body[1:-1].strip()
    if body == "":
        return []
    parts = []
    depth = 0
    in_q = None
    buf = []
    for c in body:
        if in_q:
            buf.append(c)
            if c == in_q:
                in_q = None
            continue
        if c in '"\'':
            in_q = c
            buf.append(c)
            continue
        if c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if buf:
        parts.append("".join(buf))
    return [_tpl_parse_cond_literal(p.strip()) for p in parts]


def _tpl_parse_cond_literal(text):
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


class _CondParser:
    def __init__(self, tokens, scope_chain):
        self.tokens = tokens
        self.pos = 0
        self.scope_chain = scope_chain

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def eat(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek()[0] == "OR":
            self.eat()
            right = self.parse_and()
            left = left or right
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek()[0] == "AND":
            self.eat()
            right = self.parse_not()
            left = left and right
        return left

    def parse_not(self):
        if self.peek()[0] == "NOT":
            self.eat()
            return not self.parse_not()
        return self.parse_atom()

    def parse_atom(self):
        kind, value = self.peek()
        if kind == "LP":
            self.eat()
            expr = self.parse_or()
            if self.peek()[0] != "RP":
                raise TemplateError("expected ')'")
            self.eat()
            return expr
        left = self.parse_term()
        op = self.peek()[0]
        if op in ("EQ", "NE", "IN"):
            self.eat()
            right = self.parse_term()
            if op == "EQ":
                return left == right
            if op == "NE":
                return left != right
            if op == "IN":
                try:
                    return left in right
                except TypeError:
                    return False
        return _tpl_truthy(left)

    def parse_term(self):
        kind, value = self.eat()
        if kind == "STR":
            return value
        if kind == "NUM":
            return float(value) if "." in value else int(value)
        if kind == "TRUE":
            return True
        if kind == "FALSE":
            return False
        if kind == "NULL":
            return None
        if kind == "LIST":
            return _tpl_parse_literal_list(value)
        if kind == "PATH":
            try:
                return _tpl_resolve_path(self.scope_chain, value)
            except TemplateError:
                return None  # undefined → null in conditions
        raise TemplateError("unexpected token in condition: %r" % ((kind, value),))


def _tpl_eval_cond(payload, scope_chain):
    tokens = _tpl_tokenize_cond(payload)
    return _CondParser(tokens, scope_chain).parse()


def _tpl_find_matching_end(tokens, start, expected_open_kind):
    """Given tokens[start] is T_FOR or T_IF, find the matching T_END index.

    Returns (else_idx_or_None, end_idx). Skips nested for/if blocks.
    """
    depth = 1
    else_idx = None
    i = start + 1
    while i < len(tokens):
        kind = tokens[i][0]
        if kind in (T_FOR, T_IF):
            depth += 1
        elif kind == T_END:
            depth -= 1
            if depth == 0:
                return else_idx, i
        elif kind == T_ELSE and depth == 1 and expected_open_kind == T_IF:
            else_idx = i
        i += 1
    raise TemplateError("unmatched `{{ %s ... }}` — missing `{{ end }}`" % ("for" if expected_open_kind == T_FOR else "if"))


_TPL_PARTIAL_HEAD = re.compile(r'^"([^"]+)"\s*(.*)$')
_TPL_NAMED_BINDING = re.compile(r"(\w+)\s*=\s*([\w.]+|\"[^\"]*\"|'[^']*'|true|false|null|\[.*?\])")


def _tpl_parse_partial_call(payload):
    """Parse `"name.html" [with ...]`. Returns (name, with_mode, with_payload)."""
    m = _TPL_PARTIAL_HEAD.match(payload.strip())
    if not m:
        raise TemplateError("malformed partial call: `partial %s`" % payload)
    name = m.group(1)
    rest = m.group(2).strip()
    if rest == "":
        return name, None, None
    if not rest.startswith("with "):
        raise TemplateError("expected `with` in partial call: `partial %s`" % payload)
    rest = rest[len("with ") :].strip()
    if "=" in rest:
        return name, "named", rest
    return name, "nested", rest


def _tpl_eval_named_bindings(payload, scope_chain):
    """Parse `k=v k2=v2` and resolve each value against the scope_chain."""
    out = {}
    for m in _TPL_NAMED_BINDING.finditer(payload):
        key = m.group(1)
        raw_val = m.group(2)
        if raw_val.startswith('"') and raw_val.endswith('"'):
            out[key] = raw_val[1:-1]
        elif raw_val.startswith("'") and raw_val.endswith("'"):
            out[key] = raw_val[1:-1]
        elif raw_val == "true":
            out[key] = True
        elif raw_val == "false":
            out[key] = False
        elif raw_val == "null":
            out[key] = None
        elif _YAML_INT.match(raw_val):
            out[key] = int(raw_val)
        elif _YAML_FLOAT.match(raw_val):
            out[key] = float(raw_val)
        else:
            out[key] = _tpl_resolve_path(scope_chain, raw_val)
    return out


def _tpl_parse_for_header(payload):
    """Parse 'x in coll' or 'x, i in coll'. Returns (var_names, coll_path)."""
    m = re.match(r"^(\w+)(?:\s*,\s*(\w+))?\s+in\s+(.+)$", payload.strip())
    if not m:
        raise TemplateError("malformed for: `for %s`" % payload)
    names = [m.group(1)]
    if m.group(2):
        names.append(m.group(2))
    return names, m.group(3).strip()


def _tpl_render_tokens(tokens, scope_chain, partial_lookup=None):
    out = []
    i = 0
    while i < len(tokens):
        kind, payload, pos = tokens[i]
        if kind == T_TEXT:
            out.append(payload)
            i += 1
        elif kind == T_COMMENT:
            i += 1
        elif kind == T_VAR:
            value, raw = _tpl_eval_expr(payload, scope_chain)
            if value is None:
                value = ""
            text = str(value)
            if not raw:
                text = _html_escape(text)
            out.append(text)
            i += 1
        elif kind == T_FOR:
            names, coll_path = _tpl_parse_for_header(payload)
            collection, _ = _tpl_eval_expr(coll_path, scope_chain)
            _, end_idx = _tpl_find_matching_end(tokens, i, T_FOR)
            body_tokens = tokens[i + 1 : end_idx]
            # Iterate.
            if collection is None:
                items = []
            elif isinstance(collection, dict):
                items = list(collection.items())
            else:
                items = list(collection)
            for idx, item in enumerate(items):
                loop_scope = {}
                if isinstance(collection, dict):
                    key, value = item
                    if len(names) == 1:
                        loop_scope[names[0]] = value
                    else:
                        loop_scope[names[0]] = key
                        loop_scope[names[1]] = value
                else:
                    loop_scope[names[0]] = item
                    if len(names) == 2:
                        loop_scope[names[1]] = idx
                rendered, _ = _tpl_render_tokens(
                    body_tokens, [loop_scope] + scope_chain, partial_lookup=partial_lookup
                )
                out.append(rendered)
            i = end_idx + 1
        elif kind == T_IF:
            else_idx, end_idx = _tpl_find_matching_end(tokens, i, T_IF)
            cond_value = _tpl_eval_cond(payload, scope_chain)
            if cond_value:
                body = tokens[i + 1 : else_idx if else_idx is not None else end_idx]
            elif else_idx is not None:
                body = tokens[else_idx + 1 : end_idx]
            else:
                body = []
            rendered, _ = _tpl_render_tokens(body, scope_chain, partial_lookup=partial_lookup)
            out.append(rendered)
            i = end_idx + 1
        elif kind == T_END:
            raise TemplateError("unexpected `{{ end }}` with no opener")
        elif kind == T_ELSE:
            raise TemplateError("unexpected `{{ else }}` outside `{{ if }}`")
        elif kind == T_PARTIAL:
            if partial_lookup is None:
                raise TemplateError("partial used but no partial_lookup provided")
            name, with_mode, with_payload = _tpl_parse_partial_call(payload)
            partial_text = partial_lookup(name)
            sub_tokens = list(_tpl_tokenize(partial_text))
            if with_mode == "named":
                bindings = _tpl_eval_named_bindings(with_payload, scope_chain)
                persistent = [s for s in scope_chain if isinstance(s, dict) and (
                    "page" in s or "site" in s or "data" in s
                )]
                rendered, _ = _tpl_render_tokens(
                    sub_tokens, [bindings] + persistent, partial_lookup=partial_lookup
                )
            elif with_mode == "nested":
                obj_value = _tpl_resolve_path(scope_chain, with_payload)
                name_of_obj = with_payload.split(".")[-1]
                nested_scope = {name_of_obj: obj_value}
                persistent = [s for s in scope_chain if isinstance(s, dict) and (
                    "page" in s or "site" in s or "data" in s
                )]
                rendered, _ = _tpl_render_tokens(
                    sub_tokens, [nested_scope] + persistent, partial_lookup=partial_lookup
                )
            else:
                persistent = [s for s in scope_chain if isinstance(s, dict) and (
                    "page" in s or "site" in s or "data" in s
                )]
                rendered, _ = _tpl_render_tokens(
                    sub_tokens, persistent, partial_lookup=partial_lookup
                )
            out.append(rendered)
            i += 1
        elif kind == T_LAYOUT:
            if partial_lookup is None:
                raise TemplateError("layout used but no partial_lookup provided")
            m = _TPL_PARTIAL_HEAD.match(payload.strip())
            if not m:
                raise TemplateError("malformed layout: `layout %s`" % payload)
            layout_name = m.group(1)
            # Render the REMAINING tokens as the inner.
            remaining = tokens[i + 1 :]
            inner_html, _ = _tpl_render_tokens(remaining, scope_chain, partial_lookup=partial_lookup)
            layout_text = partial_lookup(layout_name)
            layout_tokens = list(_tpl_tokenize(layout_text))
            layout_scope = [{"inner": inner_html}] + scope_chain
            rendered, _ = _tpl_render_tokens(layout_tokens, layout_scope, partial_lookup=partial_lookup)
            out.append(rendered)
            return "".join(out), len(tokens)  # layout consumes everything after it
        else:
            raise TemplateError("template construct not yet implemented: %s" % kind)
    return "".join(out), len(tokens)


def template_render(text, scope, partial_lookup=None):
    """Render `text` against `scope` (a dict). Returns the rendered string."""
    tokens = list(_tpl_tokenize(text))
    result, _ = _tpl_render_tokens(tokens, [scope], partial_lookup=partial_lookup)
    return result


# --- content ---


class Page:
    """A single source file parsed into structured form.

    Attributes:
      kind          : 'post' | 'product' | 'page' | 'section-index'
      section       : top-level dir name under content/ (e.g. 'blog', 'products', 'pages')
      slug          : filename without extension (or 'index' for _index.yaml)
      rel_path      : source file path, repo-relative under content/
      url           : absolute root-relative URL ('/...' with trailing slash, except 404.html)
      output_path   : where in dist/ this writes (e.g. 'blog/a-post/index.html')
      title         : page.title (from front matter or yaml top-level)
      description   : page.description (front matter / yaml)
      date          : datetime.date or None
      last_modified : datetime.date or None
      is_draft      : bool
      meta          : full parsed meta/yaml dict
      body_html     : rendered HTML body for posts; "" for yaml pages
      body_invocations : list of shortcode invocations from markdown_render
      raw_body      : raw Markdown body (or full YAML for non-post)
    """

    def __init__(self, **kwargs):
        self.kind = kwargs.get("kind", "page")
        self.section = kwargs.get("section", "")
        self.slug = kwargs.get("slug", "")
        self.rel_path = kwargs.get("rel_path", "")
        self.url = kwargs.get("url", "/")
        self.output_path = kwargs.get("output_path", "index.html")
        self.title = kwargs.get("title", "")
        self.description = kwargs.get("description", "")
        self.date = kwargs.get("date")
        self.last_modified = kwargs.get("last_modified")
        self.is_draft = kwargs.get("is_draft", False)
        self.meta = kwargs.get("meta", {})
        self.body_html = kwargs.get("body_html", "")
        self.body_sections = kwargs.get("body_sections", {})
        self.body_invocations = kwargs.get("body_invocations", [])
        self.raw_body = kwargs.get("raw_body", "")


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def split_front_matter(text):
    """Split `---\\nyaml\\n---\\nbody` into (meta_dict, body_str)."""
    if not text:
        return {}, ""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta_text = m.group(1)
    body = text[m.end():]
    if body.startswith("\n"):
        body = body[1:]
    meta = yaml_parse(meta_text) or {}
    return meta, body


def _parse_iso_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v))
    except ValueError:
        return None


def parse_page_source(source_text, kind, rel_path):
    """Parse one source file (already read into a string) into a Page.

    `kind` is 'md' or 'yaml'.
    `rel_path` is repo-relative path under content/, e.g. 'blog/a-post.md'.
    """
    parts = rel_path.replace("\\", "/").split("/")
    section = parts[0] if len(parts) > 1 else ""
    filename = parts[-1]
    base = filename.rsplit(".", 1)[0]
    is_section_index = base == "_index"
    slug = base if not is_section_index else "index"

    if kind == "md":
        meta, body = split_front_matter(source_text)
        invocations = []
        body_html = markdown_render(body, _invocations=invocations)
    else:
        meta = yaml_parse(source_text) or {}
        body = ""
        body_html = ""
        invocations = []

    # body_source + inline body is ambiguous — pick one source.
    if meta.get("body_source") and body.strip():
        raise BuildError(
            "%s: cannot have both an inline body and `body_source`; pick one" % rel_path,
            source=rel_path,
        )

    if is_section_index:
        page_kind = "section-index"
    elif section == "blog":
        page_kind = "post"
    elif section == "products":
        page_kind = "product"
    elif section == "pages":
        page_kind = "page"
    else:
        page_kind = "page"

    url, output_path = _compute_url_and_output(section, slug, is_section_index)

    return Page(
        kind=page_kind,
        section=section,
        slug=slug,
        rel_path=rel_path,
        url=url,
        output_path=output_path,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        date=_parse_iso_date(meta.get("date")),
        last_modified=_parse_iso_date(meta.get("updated")),
        is_draft=bool(meta.get("draft", False)),
        meta=meta,
        body_html=body_html,
        body_invocations=invocations,
        raw_body=body,
    )


def _compute_url_and_output(section, slug, is_section_index):
    """Apply the URL mapping rules from spec §4.2 + §4.6."""
    if is_section_index:
        if section == "":
            return "/", "index.html"
        return "/%s/" % section, "%s/index.html" % section
    if section == "pages":
        if slug == "home":
            return "/", "index.html"
        if slug == "404":
            return "/404.html", "404.html"
        return "/%s/" % slug, "%s/index.html" % slug
    if section == "":
        return "/%s/" % slug, "%s/index.html" % slug
    return "/%s/%s/" % (section, slug), "%s/%s/index.html" % (section, slug)


# --- build ---


class BuildError(Exception):
    """A build-time error. Includes source path when applicable."""
    def __init__(self, message, source=None, line=None):
        super().__init__(message)
        self.message = message
        self.source = source
        self.line = line


def _git_last_modified(repo_root, rel_path_under_src_content):
    """Run `git log -1 --format=%cs -- <path>`. Return a date or None."""
    src_rel = "src/content/" + rel_path_under_src_content
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%cs", "--", src_rel],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip()
    if not line:
        return None
    try:
        return datetime.date.fromisoformat(line)
    except ValueError:
        return None


def _git_has_uncommitted(repo_root, rel_path_under_src_content):
    src_rel = "src/content/" + rel_path_under_src_content
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--", src_rel],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(result.stdout.strip())


def derive_pages(cfg, pages):
    """Phase 4 — fill in derived fields; validate required fields; filter drafts.

    Returns a new list (filtered) of pages, each enriched with last_modified.
    """
    today = datetime.date.today()
    kept = []
    for page in pages:
        if page.is_draft and not cfg.include_drafts:
            continue
        if not page.title and page.kind != "section-index":
            raise BuildError(
                "%s: missing required field `title`" % page.rel_path,
                source=page.rel_path,
            )
        if (
            not page.description
            and page.kind != "section-index"
            and not (page.section == "pages" and page.slug == "404")
        ):
            raise BuildError(
                "%s: missing required field `description`" % page.rel_path,
                source=page.rel_path,
            )
        if page.last_modified is None:
            git_date = _git_last_modified(cfg.root, page.rel_path)
            if git_date is None or _git_has_uncommitted(cfg.root, page.rel_path):
                page.last_modified = today
            else:
                page.last_modified = git_date
        kept.append(page)
    return kept


class Config:
    """Resolved paths + site/data namespaces for one build invocation."""
    def __init__(self, root, site, data, check, build=None, include_drafts=False):
        self.root = Path(root)
        self.src = self.root / "src"
        self.content_dir = self.src / "content"
        self.layouts_dir = self.src / "layouts"
        self.partials_dir = self.layouts_dir / "partials"
        self.data_dir = self.src / "data"
        self.static_dir = self.src / "static"
        self.dist = self.root / "dist"
        self.cache_path = self.root / ".lintc-cache.json"
        self.site = site
        self.data = data
        self.check = check
        self.build = build if build is not None else {"plugins": {}}
        self.build_plugins = {}    # {slug: module}  populated by _setup_build_plugins
        self.build_partials = {}   # {"components/<shortcode>.html": Path}
        self.include_drafts = include_drafts


def _normalize_check_config(raw):
    """Validate + normalize raw `check` dict from lintc.yaml into typed structure.

    Returns dict with keys: email_allowlist (list), stray_markers (list), plugins (dict).
    Raises BuildError on type mismatch.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BuildError(
            "lintc.yaml: top-level `check` must be a mapping, got %s" % type(raw).__name__,
            source="src/data/lintc.yaml",
        )

    # email_allowlist: list[str], default []
    email_allowlist = raw.get("email_allowlist")
    if email_allowlist is None:
        email_allowlist = []
    elif not isinstance(email_allowlist, list):
        raise BuildError(
            "lintc.yaml: check.email_allowlist must be a list of strings, got %s"
            % type(email_allowlist).__name__,
            source="src/data/lintc.yaml",
        )

    # stray_markers: list[str]; missing → defaults; empty list → no check
    if "stray_markers" not in raw or raw["stray_markers"] is None:
        stray_markers = list(DEFAULT_STRAY_MARKERS)
    elif not isinstance(raw["stray_markers"], list):
        raise BuildError(
            "lintc.yaml: check.stray_markers must be a list of strings, got %s"
            % type(raw["stray_markers"]).__name__,
            source="src/data/lintc.yaml",
        )
    else:
        stray_markers = list(raw["stray_markers"])

    # plugins: dict[slug → dict], default {}
    plugins = raw.get("plugins")
    if plugins is None:
        plugins = {}
    elif not isinstance(plugins, dict):
        raise BuildError(
            "lintc.yaml: check.plugins must be a mapping, got %s"
            % type(plugins).__name__,
            source="src/data/lintc.yaml",
        )

    # Warn on unknown keys (forward-compat: v0.3+ may add fields).
    KNOWN_KEYS = {"email_allowlist", "stray_markers", "plugins"}
    unknown = sorted(set(raw.keys()) - KNOWN_KEYS)
    for key in unknown:
        sys.stderr.write("lintc.yaml: warning: ignoring unknown key `check.%s`\n" % key)
    return {
        "email_allowlist": email_allowlist,
        "stray_markers": stray_markers,
        "plugins": plugins,
    }


def _normalize_build_config(raw):
    """Validate + normalize raw `build` dict from lintc.yaml.

    Returns dict with key: plugins (dict[slug -> config-dict]).
    Raises BuildError on type mismatch.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BuildError(
            "lintc.yaml: top-level `build` must be a mapping, got %s" % type(raw).__name__,
            source="src/data/lintc.yaml",
        )
    plugins = raw.get("plugins")
    if plugins is None:
        plugins = {}
    elif not isinstance(plugins, dict):
        raise BuildError(
            "lintc.yaml: build.plugins must be a mapping, got %s" % type(plugins).__name__,
            source="src/data/lintc.yaml",
        )
    KNOWN_KEYS = {"plugins"}
    for key in sorted(set(raw.keys()) - KNOWN_KEYS):
        sys.stderr.write("lintc.yaml: warning: ignoring unknown key `build.%s`\n" % key)
    return {"plugins": plugins}


def _setup_build_plugins(cfg):
    pass


def load_config(root, include_drafts=False):
    """Phase 1 — load src/data/*.yaml; resolve paths; normalize check config."""
    root = Path(root)
    data_dir = root / "src" / "data"
    site = {}
    data = {}
    raw_check = None
    raw_build = None
    if data_dir.is_dir():
        for path in sorted(data_dir.glob("*.yaml")):
            stem = path.stem
            value = yaml_parse(path.read_text(encoding="utf-8"))
            if stem == "site":
                site = value or {}
            elif stem == "lintc":
                # Pull out the `check` and `build` subsections for normalization;
                # do not expose them on cfg.data (lintc config is tool config,
                # not template data).
                if isinstance(value, dict):
                    raw_check = value.get("check")
                    raw_build = value.get("build")
            else:
                data[stem] = value or {}
    check = _normalize_check_config(raw_check)
    build = _normalize_build_config(raw_build)
    cfg = Config(root, site, data, check, build=build, include_drafts=include_drafts)
    _setup_build_plugins(cfg)
    return cfg


def discover_pages(cfg):
    """Phase 2 — walk content/ → list of Page objects (parsed via Phase 3 inline)."""
    if not cfg.content_dir.is_dir():
        return []
    pages = []
    for path in sorted(cfg.content_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(cfg.content_dir).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if any(part.startswith("_") and not part.startswith("_index.") for part in rel.split("/")[:-1]):
            continue
        if path.suffix == ".md":
            kind = "md"
        elif path.suffix in (".yaml", ".yml"):
            kind = "yaml"
        else:
            continue
        text = path.read_text(encoding="utf-8")
        page = parse_page_source(text, kind=kind, rel_path=rel)
        pages.append(page)
    return pages


def _select_layout(cfg, page):
    """Apply spec §4.6 layout selection rules. Returns Path of the layout to use."""
    # 1. Front-matter override.
    explicit = page.meta.get("layout")
    if explicit:
        path = cfg.layouts_dir / ("%s.html" % explicit)
        if path.exists():
            return path
        raise BuildError(
            "%s: front-matter `layout: %s` → %s does not exist"
            % (page.rel_path, explicit, path),
            source=page.rel_path,
        )
    # 2. Default by source kind.
    layouts = cfg.layouts_dir
    if page.kind == "section-index":
        candidate = layouts / ("%s-index.html" % page.section)
        if candidate.exists():
            return candidate
    elif page.kind == "post":
        candidate = layouts / "blog-post.html"
        if candidate.exists():
            return candidate
    elif page.kind == "product":
        candidate = layouts / "product.html"
        if candidate.exists():
            return candidate
    elif page.section == "pages":
        candidate = layouts / ("%s.html" % page.slug)
        if candidate.exists():
            return candidate
    else:
        candidate = layouts / ("%s.html" % page.section)
        if candidate.exists():
            return candidate
    # 3. Fallback.
    fallback = layouts / "page.html"
    if fallback.exists():
        return fallback
    raise BuildError(
        "%s: no layout found; tried section-specific + page.html" % page.rel_path,
        source=page.rel_path,
    )


def _make_partial_lookup(cfg):
    """Return a callable that resolves partial names to template text.

    Partials live under src/layouts/partials/ for "partial X" calls;
    layouts (for the `layout` directive) live under src/layouts/.
    The lookup tries partials first, then layouts.
    """
    def lookup(name):
        candidates = [
            cfg.partials_dir / name,
            cfg.layouts_dir / name,
        ]
        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8")
        raise TemplateError(
            "partial `%s` not found (looked in %s)"
            % (name, ", ".join(str(c) for c in candidates))
        )
    return lookup


def _resolve_shortcodes(html, invocations, cfg):
    """Replace shortcode sentinels (\\x00SC<id>\\x00) with rendered partials.

    Loops until no sentinels remain (or until max_iters), so nested shortcodes
    (a block whose inner contains an inline shortcode) resolve correctly.
    The sentinel format is \\x00SC<id>\\x00 — id only, no embedded inner — so
    the regex is safe even when inner_html itself contains shortcode sentinels.
    """
    if not invocations:
        return html
    sentinel_re = re.compile(r"\x00SC(\d+)\x00")
    lookup = _make_partial_lookup(cfg)

    def _resolve(m):
        idx = int(m.group(1))
        inv = invocations[idx]
        partial_path = "components/%s.html" % inv["name"]
        try:
            text = lookup(partial_path)
        except TemplateError as e:
            raise BuildError(
                "unknown shortcode `%s`" % inv["name"],
                source=None,
            ) from e
        scope = dict(inv["attrs"])
        scope["inner"] = inv["inner"]
        return template_render(text, scope, partial_lookup=lookup)

    # Loop in case any inner_html contains additional sentinels (nested shortcodes).
    for _ in range(10):  # max nesting depth — sane limit
        new_html = sentinel_re.sub(_resolve, html)
        if new_html == html:
            return new_html
        html = new_html
    return html


_H2_RE = re.compile(r'<h2[^>]*>(.*?)</h2>', re.DOTALL)


def _split_body_html_by_h2(body_html):
    """Parse rendered HTML into a dict keyed by h2 heading text.

    Returns {heading_text: html_body_until_next_h2}. Content before the first
    h2 is discarded. Inline markup in heading text is stripped to plain text.
    Last-write-wins on duplicate headings.
    """
    if not body_html:
        return {}
    matches = list(_H2_RE.finditer(body_html))
    if not matches:
        return {}
    sections = {}
    for i, m in enumerate(matches):
        heading_raw = m.group(1)
        heading_text = re.sub(r'<[^>]+>', '', heading_raw).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(body_html)
        sections[heading_text] = body_html[body_start:body_end].strip()
    return sections


def render_page(cfg, page, all_pages):
    """Phase 5 — render one Page to HTML."""
    layout_path = _select_layout(cfg, page)
    layout_text = layout_path.read_text(encoding="utf-8")
    lookup = _make_partial_lookup(cfg)

    # body_source: if set, read the file and render as Markdown for page.body_html.
    body_source_path = page.meta.get("body_source")
    if body_source_path and not page.body_html:
        resolved = (cfg.src / body_source_path).resolve()
        if not resolved.exists():
            raise BuildError(
                "%s: body_source `%s` does not exist (expected at %s)"
                % (page.rel_path, body_source_path, resolved),
                source=page.rel_path,
            )
        body_md = resolved.read_text(encoding="utf-8")
        invocations = list(page.body_invocations or [])
        page.body_html = markdown_render(body_md, _invocations=invocations)
        page.body_invocations = invocations

    # Resolve shortcodes in the body BEFORE template rendering (so they're plain HTML by then).
    page.body_html = _resolve_shortcodes(page.body_html, page.body_invocations, cfg)

    # Parse rendered body HTML into sections keyed by h2 text (v0.4+).
    page.body_sections = _split_body_html_by_h2(page.body_html)

    scope = {
        "page": _page_to_scope_dict(page),
        "site": cfg.site,
        "data": cfg.data,
        "sections": _build_sections_map(all_pages),
        "lintc": {"version": __version__},
    }
    if page.kind == "section-index":
        scope["section"] = _section_for_index(page, all_pages)
    return template_render(layout_text, scope, partial_lookup=lookup)


def _page_to_scope_dict(page):
    """Project the Page object into a dict templates can read."""
    base = dict(page.meta)  # includes user-defined fields
    base.update({
        "title": page.title,
        "description": page.description,
        "url": page.url,
        "section": page.section,
        "slug": page.slug,
        "date": page.date,
        "last_modified": page.last_modified,
        "is_draft": page.is_draft,
        "body_html": page.body_html,
        "body_sections": page.body_sections,
        "meta": page.meta,
    })
    return base


def _section_for_index(index_page, all_pages):
    """Build the {title, description, children: [page-dicts...]} for a section index."""
    section_name = index_page.section
    sort_key = index_page.meta.get("sort", "-date")
    descending = sort_key.startswith("-")
    field = sort_key.lstrip("-")
    children = [
        _page_to_scope_dict(p)
        for p in all_pages
        if p.section == section_name and p.kind != "section-index"
    ]
    children.sort(
        key=lambda c: c.get(field) or datetime.date.min,
        reverse=descending,
    )
    return {
        "title": index_page.title,
        "description": index_page.description,
        "intro": index_page.meta.get("intro", ""),
        "children": children,
    }


def _build_sections_map(all_pages):
    """All sections keyed by name; each value matches _section_for_index's shape."""
    by_section = {}
    for p in all_pages:
        if p.kind == "section-index":
            # Ensure sections with an index but no children still appear.
            by_section.setdefault(p.section, [])
            continue
        by_section.setdefault(p.section, []).append(p)

    sections = {}
    for name, pages in by_section.items():
        idx = next(
            (p for p in all_pages
             if p.kind == "section-index" and p.section == name),
            None,
        )
        sort_key = (idx.meta.get("sort") if idx else None) or "-date"
        descending = sort_key.startswith("-")
        field = sort_key.lstrip("-")
        children = [_page_to_scope_dict(p) for p in pages]
        children.sort(
            key=lambda c: c.get(field) or datetime.date.min,
            reverse=descending,
        )
        sections[name] = {
            "title":       idx.title if idx else name,
            "description": idx.description if idx else "",
            "intro":       (idx.meta.get("intro") if idx else "") or "",
            "children":    children,
        }
    return sections


class BuildResult:
    def __init__(self):
        self.pages_built = []
        self.assets_copied = []
        self.errors = []
        self.warnings = []


def _ensure_parent(path):
    path.parent.mkdir(parents=True, exist_ok=True)


def emit_page(cfg, page, html):
    """Phase 6 (per page) — write the rendered HTML to dist/<output_path>."""
    out_path = cfg.dist / page.output_path
    _ensure_parent(out_path)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _copy_static(cfg):
    """Copy src/static/* verbatim to dist/. Returns list of (rel, dest) tuples."""
    copied = []
    if not cfg.static_dir.is_dir():
        return copied
    for path in cfg.static_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(cfg.static_dir).as_posix()
        dest = cfg.dist / rel
        _ensure_parent(dest)
        shutil.copy2(path, dest)
        copied.append((rel, dest))
    return copied


def _emit_sitemap(cfg, pages):
    """Generate dist/sitemap.xml from non-draft, non-404 pages."""
    base = cfg.site.get("base_url", "").rstrip("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for page in pages:
        # Exclude 404 (it has a non-trailing-slash URL ending in .html).
        if page.url.endswith(".html"):
            continue
        lastmod = page.last_modified.isoformat() if page.last_modified else ""
        lines.append("  <url>")
        lines.append("    <loc>%s%s</loc>" % (base, page.url))
        if lastmod:
            lines.append("    <lastmod>%s</lastmod>" % lastmod)
        lines.append("  </url>")
    lines.append("</urlset>")
    out_path = cfg.dist / "sitemap.xml"
    _ensure_parent(out_path)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _prune_orphans(cfg, kept_paths):
    """Delete files in dist/ that aren't in `kept_paths`."""
    kept = {p.resolve() for p in kept_paths}
    if not cfg.dist.is_dir():
        return
    for path in list(cfg.dist.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() not in kept:
            try:
                path.unlink()
            except OSError:
                pass
    # Remove now-empty subdirectories.
    for path in sorted(cfg.dist.rglob("*"), key=lambda p: -len(p.parts)):
        if path.is_dir() and not any(path.iterdir()):
            try:
                path.rmdir()
            except OSError:
                pass


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HREF_SRC_RE = re.compile(r'(?:href|src)="([^"]*)"')
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#", "data:")


def _validate_post_emit(cfg, mode="build"):
    """Run post-emit validations across dist/. Returns (errors, warnings).

    Reads `stray_markers` and `email_allowlist` from cfg.check (set during
    config load). Empty lists disable that check entirely. Broken internal
    links are always checked regardless of config.

    In serve mode, stray markers and foreign emails are warnings, not errors.
    """
    errors = []
    warnings = []
    dist = cfg.dist
    if not dist.is_dir():
        return errors, warnings
    stray_markers = cfg.check.get("stray_markers", [])
    email_allowlist = cfg.check.get("email_allowlist", [])
    files = list(dist.rglob("*.html")) + list(dist.rglob("*.xml"))
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(dist).as_posix()
        # Broken internal links (always on).
        for m in _HREF_SRC_RE.finditer(text):
            target = m.group(1)
            if not target or target.startswith(_SKIP_PREFIXES):
                continue
            target_clean = target.split("?", 1)[0].split("#", 1)[0]
            if target_clean.startswith("/"):
                base = dist / target_clean.lstrip("/")
            else:
                base = path.parent / target_clean
            if target_clean.endswith("/"):
                base = base / "index.html"
            elif base.is_dir():
                base = base / "index.html"
            if not base.exists():
                errors.append("%s: broken internal link `%s`" % (rel, target))
        # Stray markers (config-driven; empty list disables).
        for marker in stray_markers:
            if marker in text:
                msg = "%s: stray marker `%s`" % (rel, marker)
                if mode == "serve":
                    warnings.append(msg)
                else:
                    errors.append(msg)
        # Email allowlist (config-driven; empty list disables).
        if email_allowlist:
            for m in _EMAIL_RE.finditer(text):
                addr = m.group(0)
                if not any(addr.endswith(pattern) for pattern in email_allowlist):
                    msg = "%s: email `%s` not in allowlist" % (rel, addr)
                    if mode == "serve":
                        warnings.append(msg)
                    else:
                        errors.append(msg)
    return errors, warnings


def _load_cache(cfg):
    if not cfg.cache_path.exists():
        return {"version": 1, "files": {}}
    try:
        data = json.loads(cfg.cache_path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return {"version": 1, "files": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "files": {}}


def _save_cache(cfg, cache):
    try:
        cfg.cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError:
        pass


def _hash_source(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _update_cache_entry(cache, page, output_paths, source_text):
    cache["files"][page.rel_path] = {
        "mtime": time.time(),
        "hash": _hash_source(source_text),
        "outputs": [str(p) for p in output_paths],
    }


def build_site(root, include_drafts=False):
    """Top-level build entry point. Returns a BuildResult."""
    result = BuildResult()
    try:
        cfg = load_config(root, include_drafts=include_drafts)
        cfg.dist.mkdir(parents=True, exist_ok=True)
        cache = _load_cache(cfg)
        pages = discover_pages(cfg)
        pages = derive_pages(cfg, pages)
        kept_outputs = []
        for page in pages:
            html = render_page(cfg, page, pages)
            out_path = emit_page(cfg, page, html)
            result.pages_built.append(page)
            kept_outputs.append(out_path)
            source_text = (cfg.content_dir / page.rel_path).read_text(encoding="utf-8")
            _update_cache_entry(cache, page, [out_path], source_text)
        for rel, dest in _copy_static(cfg):
            result.assets_copied.append(rel)
            kept_outputs.append(dest)
        sitemap_path = _emit_sitemap(cfg, pages)
        kept_outputs.append(sitemap_path)
        validation_errors, validation_warnings = _validate_post_emit(cfg, mode="build")
        result.errors.extend(validation_errors)
        result.warnings.extend(validation_warnings)
        _prune_orphans(cfg, kept_outputs)
        _save_cache(cfg, cache)
    except (BuildError, TemplateError, YamlError) as exc:
        result.errors.append(str(exc))
    return result


# --- server ---

LIVERELOAD_SCRIPT = b"""<script data-livereload>
(function () {
  if (!window.EventSource) return;
  var es = new EventSource("/__livereload");
  es.addEventListener("reload", function () { location.reload(); });
  es.addEventListener("error-overlay", function (ev) {
    try { showOverlay(JSON.parse(ev.data)); } catch (e) {}
  });
  es.addEventListener("clear-overlay", function () { hideOverlay(); });
  function showOverlay(data) {
    hideOverlay();
    var d = document.createElement("div");
    d.id = "__lintc_overlay";
    d.style.cssText = "position:fixed;inset:0;z-index:99999;background:#180000;color:#ff8;font:14px/1.4 ui-monospace,monospace;padding:24px;overflow:auto;white-space:pre-wrap;";
    d.textContent = (data.title || "Build error") + "\\n\\n" + (data.detail || "");
    document.body.appendChild(d);
  }
  function hideOverlay() {
    var d = document.getElementById("__lintc_overlay");
    if (d) d.parentNode.removeChild(d);
  }
})();
</script>
"""


def inject_livereload(body_bytes, enabled=True):
    """Insert the live-reload snippet into an HTML body (bytes in, bytes out)."""
    if not enabled:
        return body_bytes
    marker = b"</body>"
    idx = body_bytes.lower().rfind(marker)
    if idx == -1:
        return body_bytes + LIVERELOAD_SCRIPT
    return body_bytes[:idx] + LIVERELOAD_SCRIPT + body_bytes[idx:]


class Reloader:
    """Tracks the most recent event to broadcast over SSE.

    State is (gen, kind, payload) where kind is 'reload', 'error-overlay', or
    'clear-overlay'. Each bump increments gen so SSE clients can resume.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._gen = 0
        self._kind = "reload"
        self._payload = None

    def current(self):
        with self._cond:
            return self._gen

    def snapshot(self):
        with self._cond:
            return self._gen, self._kind, self._payload

    def bump_reload(self):
        with self._cond:
            self._gen += 1
            self._kind = "reload"
            self._payload = None
            self._cond.notify_all()

    def set_error(self, payload):
        with self._cond:
            self._gen += 1
            self._kind = "error-overlay"
            self._payload = payload
            self._cond.notify_all()

    def clear_error(self):
        with self._cond:
            self._gen += 1
            self._kind = "clear-overlay"
            self._payload = None
            self._cond.notify_all()

    def wait_past(self, gen, timeout):
        """Block until gen advances. Returns (new_gen, kind, payload)."""
        with self._cond:
            self._cond.wait_for(lambda: self._gen > gen, timeout=timeout)
            return self._gen, self._kind, self._payload


def start_watcher(cfg, reloader, on_change, interval=0.3):
    """Start a background thread that polls src/ for changes.

    `on_change(changed_paths: list[Path])` is called from the watcher thread
    whenever any source file changes.
    """
    src = cfg.src

    def snapshot():
        snap = {}
        if not src.is_dir():
            return snap
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            if any(part.startswith(".") or part == "__pycache__" for part in rel.split("/")):
                continue
            if path.name.endswith((".swp", ".pyc")):
                continue
            try:
                snap[rel] = path.stat().st_mtime
            except OSError:
                pass
        return snap

    def loop():
        prev = snapshot()
        while True:
            time.sleep(interval)
            cur = snapshot()
            if cur != prev:
                added = set(cur) - set(prev)
                removed = set(prev) - set(cur)
                modified = {k for k in cur.keys() & prev.keys() if cur[k] != prev[k]}
                changed = sorted(added | removed | modified)
                prev = cur
                try:
                    on_change([src / p for p in changed])
                except Exception:
                    pass

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


class LintcHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler that injects the live-reload client and handles SSE."""

    reloader = None  # set on the class before the server starts
    inject_enabled = True

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".webmanifest": "application/manifest+json",
    }

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s  %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/__livereload":
            self._serve_sse()
            return
        local = self.translate_path(self.path)
        if os.path.isdir(local):
            if not path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.end_headers()
                return
            local = os.path.join(local, "index.html")
            if not os.path.isfile(local):
                self._serve_404()
                return
        if not os.path.isfile(local):
            self._serve_404()
            return
        if local.endswith((".html", ".htm")):
            self._serve_html(local, status=200)
        else:
            self._serve_file(local)

    def _serve_html(self, local, status):
        try:
            with open(local, "rb") as f:
                body = f.read()
        except OSError:
            self._serve_404()
            return
        body = inject_livereload(body, enabled=self.inject_enabled)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve_file(self, local):
        try:
            f = open(local, "rb")
        except OSError:
            self._serve_404()
            return
        try:
            fs = os.fstat(f.fileno())
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(local))
            self.send_header("Content-Length", str(fs.st_size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.copyfile(f, self.wfile)
        finally:
            f.close()

    def _serve_404(self):
        custom = os.path.join(self.directory, "404.html")
        if os.path.isfile(custom):
            self._serve_html(custom, status=404)
        else:
            self.send_error(404, "Not Found")

    def _serve_sse(self):
        if self.reloader is None:
            self.send_error(500, "no reloader")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        gen = self.reloader.current()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                new, kind, payload = self.reloader.wait_past(gen, timeout=15)
                if new > gen:
                    gen = new
                    body = json.dumps(payload) if payload is not None else "{}"
                    self.wfile.write(
                        b"event: %s\ndata: %s\n\n" % (kind.encode("ascii"), body.encode("utf-8"))
                    )
                else:
                    self.wfile.write(b": ping\n\n")  # keep-alive
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# Errno is OS-specific; symbol names are portable. Keep the tuple narrow:
# only catch client-disconnect errors here, never blanket Exception.
_CLIENT_DISCONNECT_EXC = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


class LintcHTTPServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer that prints a one-line friendly message instead of
    a multi-line traceback when the client disconnects mid-request.

    The default `socketserver.BaseServer.handle_error` dumps the full Python
    traceback to stderr for ANY exception escaping the request handler. For
    a static dev server, the overwhelmingly common cause is the browser
    killing a keep-alive connection (or the livereload SSE long-poll) — a
    normal client behavior, not a server bug. Show one line for those, fall
    through to the default for anything else.
    """

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_DISCONNECT_EXC):
            host = client_address[0] if client_address else "?"
            port = client_address[1] if len(client_address) > 1 else 0
            sys.stderr.write(
                "  %s  client %s:%d disconnected (%s)\n"
                % (time.strftime("%d/%b/%Y %H:%M:%S"), host, port, type(exc).__name__)
            )
            return
        super().handle_error(request, client_address)


def run_server(cfg, host="127.0.0.1", port=8000, inject_enabled=True):
    """Start an HTTP server (foreground) serving cfg.dist/."""
    reloader = Reloader()

    def on_change(changed):
        result = build_site(cfg.root, include_drafts=cfg.include_drafts)
        if result.errors:
            reloader.set_error({
                "title": "Build error",
                "detail": "\n".join(result.errors),
            })
        else:
            reloader.bump_reload()

    start_watcher(cfg, reloader, on_change)

    LintcHandler.reloader = reloader
    LintcHandler.inject_enabled = inject_enabled

    from functools import partial
    handler = partial(LintcHandler, directory=str(cfg.dist))
    try:
        httpd = LintcHTTPServer((host, port), handler)
    except OSError as exc:
        raise BuildError(
            "cannot bind %s:%d (%s) — try --port" % (host, port, exc)
        )
    httpd.daemon_threads = True

    sys.stderr.write("%s serve\n" % TOOL_NAME)
    sys.stderr.write("  serving : %s\n" % cfg.dist)
    sys.stderr.write("  watching: %s\n" % cfg.src)
    sys.stderr.write("  url     : http://%s:%d/\n" % (host, port))
    sys.stderr.write("  stop    : Ctrl-C\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopped.\n")
    finally:
        httpd.server_close()


# --- plugins ---
def discover_plugins():
    """Return {slug: callable} for every module in `lintc_plugins` exposing `run`.

    Slugs are filenames with underscores converted to hyphens
    (e.g. `remote_sync.py` → `remote-sync`). Files starting with
    `_` (incl. `__init__.py`) are skipped.

    Future PyPI plugin packages contribute to the same `lintc_plugins`
    namespace via PEP 420; this discovery finds them transparently.

    Returns an empty dict if `lintc_plugins` isn't importable.
    """
    plugins = {}
    try:
        import lintc_plugins
    except ImportError:
        return plugins
    for plugin_dir in lintc_plugins.__path__:
        path = Path(plugin_dir)
        if not path.is_dir():
            # In editable installs, __path__ can contain finder-hook strings
            # like "__editable__.lintc-0.2.0.finder.__path_hook__" that aren't
            # real filesystem paths. Skip them.
            continue
        for entry in path.iterdir():
            if entry.suffix != ".py" or entry.name.startswith("_"):
                continue
            stem = entry.stem
            try:
                mod = importlib.import_module("lintc_plugins." + stem)
            except ImportError:
                continue
            if hasattr(mod, "run") and callable(mod.run):
                slug = stem.replace("_", "-")
                plugins[slug] = mod.run
    return plugins


# --- check ---
def run_check(cfg):
    """Top-level `lintc check`: run enabled plugins, build to temp, run Layer 1.

    Plugins run BEFORE the build so plugins that write files (e.g.,
    remote-sync writing body_source targets) make their output available
    to subsequent rendering.

    Returns (errors, warnings).
    """
    import tempfile
    errors = []
    warnings = []
    # Plugins first.
    plugin_configs = cfg.check.get("plugins", {})
    if plugin_configs:
        discovered = discover_plugins()
        for slug, plugin_config in plugin_configs.items():
            if slug not in discovered:
                available = sorted(discovered.keys()) or ["(none discovered)"]
                raise BuildError(
                    "lintc.yaml: plugin `%s` not found; available: %s"
                    % (slug, ", ".join(available)),
                    source="src/data/lintc.yaml",
                )
            plugin_errors, plugin_warnings = discovered[slug](cfg, plugin_config or {})
            errors.extend(plugin_errors)
            warnings.extend(plugin_warnings)
    # Build + Layer 1.
    with tempfile.TemporaryDirectory(prefix="lintc-check-") as tmp:
        tmp_path = Path(tmp)
        original_dist = cfg.dist
        cfg.dist = tmp_path
        try:
            cfg.dist.mkdir(parents=True, exist_ok=True)
            pages = derive_pages(cfg, discover_pages(cfg))
            for page in pages:
                html = render_page(cfg, page, pages)
                emit_page(cfg, page, html)
            _copy_static(cfg)
            _emit_sitemap(cfg, pages)
            post_errors, post_warnings = _validate_post_emit(cfg, mode="build")
            errors.extend(post_errors)
            warnings.extend(post_warnings)
        finally:
            cfg.dist = original_dist
    return errors, warnings


# --- cli ---
def cli(argv=None):
    parser = argparse.ArgumentParser(prog=TOOL_NAME)
    parser.add_argument("--version", action="version", version="%s %s" % (TOOL_NAME, TOOL_VERSION))
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build", help="full production build")
    build.add_argument("--root", default=".", help="repo root (default: cwd)")
    build.add_argument("--include-drafts", action="store_true")

    serve = sub.add_parser("serve", help="dev server with live reload")
    serve.add_argument("--root", default=".")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-reload", action="store_true")
    serve.add_argument("--no-drafts", action="store_true",
                       help="hide drafts (default is to include them in serve mode)")

    check = sub.add_parser("check", help="post-emit validations + GitHub repo parity")
    check.add_argument("--root", default=".")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "build":
        result = build_site(args.root, include_drafts=args.include_drafts)
        _print_build_summary(result)
        return 1 if result.errors else 0

    if args.command == "serve":
        include_drafts = not args.no_drafts
        cfg = load_config(args.root, include_drafts=include_drafts)
        cfg.dist.mkdir(parents=True, exist_ok=True)
        initial = build_site(args.root, include_drafts=include_drafts)
        _print_build_summary(initial)
        try:
            run_server(cfg, host=args.host, port=args.port,
                       inject_enabled=not args.no_reload)
        except BuildError as exc:
            sys.stderr.write("error: %s\n" % exc)
            return 1
        return 0

    if args.command == "check":
        cfg = load_config(args.root, include_drafts=False)
        errors, warnings = run_check(cfg)
        for w in warnings:
            sys.stderr.write("warn: %s\n" % w)
        for e in errors:
            sys.stderr.write("fail: %s\n" % e)
        if errors:
            sys.stderr.write("\n%d check%s failed.\n" % (len(errors), "" if len(errors) == 1 else "s"))
            return 1
        sys.stderr.write("All checks passed.\n")
        return 0

    return 0


def _print_build_summary(result):
    sys.stderr.write("%s build — %d pages, %d assets\n" % (
        TOOL_NAME, len(result.pages_built), len(result.assets_copied),
    ))
    for w in result.warnings:
        sys.stderr.write("  warn: %s\n" % w)
    for e in result.errors:
        sys.stderr.write("  fail: %s\n" % e)


# --- main ---
if __name__ == "__main__":
    sys.exit(cli())
