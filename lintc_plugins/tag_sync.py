"""Tag-sync — set a content YAML's `version:` field from a repo's latest tag.

For each configured (repo, local) mapping, fetches the repo's tags via
`git ls-remote --tags`, picks the highest semver release tag (skipping
pre-releases), and rewrites the top-level `version:` line in the local file.
Tracks last-synced tags in a committed lockfile so drift surfaces via git
working-tree state — review with `git diff` before committing. Runs at
`lintc check`, like remote-sync.

Disabled by default. Enable via src/data/lintc.yaml:

    check:
      plugins:
        tag-sync:
          mappings:
            - { repo: owner/name, local: src/content/products/foo.yaml }
            # optional per-mapping: field: version   (default "version")
"""
import datetime
import re
import subprocess


LOCKFILE_REL_PATH = "src/data/lintc-tag.lock"
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def run(cfg, plugin_config):
    """Sync each mapping's `version:` field from its repo's latest tag."""
    mappings = plugin_config.get("mappings")
    if mappings is None:
        return (["tag-sync: `mappings` is required in plugin config"], [])
    if not isinstance(mappings, list):
        return (["tag-sync: `mappings` must be a list of {repo, local} dicts"], [])
    if not mappings:
        return ([], [])

    errors = []
    warnings = []
    lockfile_path = cfg.root / LOCKFILE_REL_PATH
    lock_data = _read_lockfile(lockfile_path)
    lock_modified = False

    for i, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append(
                "tag-sync: mappings[%d] must be a dict with `repo` and `local` keys" % i
            )
            continue
        repo = mapping.get("repo")
        local = mapping.get("local")
        field = mapping.get("field", "version")
        if not repo or not local:
            errors.append(
                "tag-sync: mappings[%d] missing required `repo` or `local`" % i
            )
            continue

        tag = _latest_tag(repo)
        if tag is None:
            warnings.append(
                "tag-sync: no tag fetched for " + repo
                + " — leaving " + local + " unchanged"
            )
            continue

        local_full = cfg.root / local
        if not local_full.exists():
            warnings.append("tag-sync: " + local + " does not exist — skipping")
            continue

        text = local_full.read_text(encoding="utf-8")
        new_text = _rewrite_field(text, field, tag)
        if new_text is None:
            warnings.append(
                "tag-sync: " + local + ": no top-level `" + field + ":` line — skipping"
            )
            continue

        if new_text != text:
            local_full.write_text(new_text, encoding="utf-8")
            lock_data["entries"][local] = {
                "repo": repo, "tag": tag, "fetched_at": _now_iso(),
            }
            lock_modified = True
            warnings.append(
                "tag-sync: set " + field + " to " + tag + " in " + local
                + " — review with `git diff` and commit"
            )
        else:
            entry = lock_data["entries"].get(local)
            if entry is None or entry.get("tag") != tag:
                lock_data["entries"][local] = {
                    "repo": repo, "tag": tag, "fetched_at": _now_iso(),
                }
                lock_modified = True

    if lock_modified:
        _write_lockfile(lockfile_path, lock_data)
    return errors, warnings


# --- tag fetch + selection (Task 2 fills _select_latest_tag; Task 4 _fetch_tags) ---

def _latest_tag(repo):
    names = _fetch_tags(repo)
    if names is None:
        return None
    return _select_latest_tag(names)


def _fetch_tags(repo):
    """Return a list of tag names for `owner/name` via `git ls-remote --tags`,
    or None on any failure (missing git, network error, non-zero exit)."""
    url = "https://github.com/" + repo
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    names = []
    for line in result.stdout.splitlines():
        parts = line.split("\trefs/tags/")
        if len(parts) != 2:
            continue
        ref = parts[1].strip()
        if ref.endswith("^{}"):
            continue
        names.append(ref)
    return names


def _select_latest_tag(names):
    """Return the highest semver tag (vX.Y.Z), skipping pre-releases and
    non-semver names. None if there is no qualifying tag."""
    best = None
    best_key = None
    for name in names:
        m = _SEMVER_RE.match(name)
        if not m:
            continue  # pre-releases (vX.Y.Z-rc1) and non-semver are excluded
        key = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if best_key is None or key > best_key:
            best_key = key
            best = name
    return best


def _rewrite_field(text, field, value):
    """Replace the value of the first top-level `<field>:` line (anchored at
    column 0, so prefixed keys like `language_versions:` never match). Returns
    the new text, or None if no such line exists."""
    pattern = re.compile(r"(?m)^" + re.escape(field) + r":[^\n]*$")
    if not pattern.search(text):
        return None
    return pattern.sub(lambda m: field + ": " + value, text, count=1)


# --- lockfile (mirror remote_sync.py) ---

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
        "# Auto-generated by the lintc tag-sync plugin.",
        "# Commit this file. Do not edit manually.",
        "version: " + str(lock_data.get("version", 1)),
        "entries:",
    ]
    for local in sorted(lock_data["entries"].keys()):
        entry = lock_data["entries"][local]
        lines.append("  " + _quote_yaml_key(local) + ":")
        lines.append("    repo: " + _quote_yaml_str(entry["repo"]))
        lines.append("    tag: " + _quote_yaml_str(entry["tag"]))
        lines.append("    fetched_at: " + entry["fetched_at"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _quote_yaml_key(s):
    if any(c in s for c in [":", "#", "{", "}", "[", "]", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _quote_yaml_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
