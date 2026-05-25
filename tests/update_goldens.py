#!/usr/bin/env python3
"""Regenerate fixtures/<name>/expected/ by running lintc against fixtures/<name>/input/.

Usage:
    python3 tools/lintc-tests/update_goldens.py                # update all fixtures
    python3 tools/lintc-tests/update_goldens.py minimal        # update one fixture by name
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def update_fixture(name):
    fixture_root = FIXTURES_DIR / name
    input_dir = fixture_root / "input"
    expected_dir = fixture_root / "expected"
    if not input_dir.is_dir():
        sys.exit("error: fixtures/%s/input does not exist" % name)
    # Build into a temp root that mirrors the fixture layout (src/ at top, dist/ output).
    with tempfile.TemporaryDirectory(prefix="lintc-golden-") as tmp:
        tmp_root = Path(tmp)
        shutil.copytree(input_dir, tmp_root / "src")
        result = lintc.build_site(tmp_root)
        if result.errors:
            sys.exit("\n".join(result.errors))
        # Mirror tmp/dist → fixtures/<name>/expected
        if expected_dir.exists():
            shutil.rmtree(expected_dir)
        shutil.copytree(tmp_root / "dist", expected_dir)
        print("Updated %s (%d pages, %d assets)" % (name, len(result.pages_built), len(result.assets_copied)))


def main():
    if len(sys.argv) > 1:
        names = sys.argv[1:]
    else:
        names = [p.name for p in FIXTURES_DIR.iterdir() if p.is_dir() and (p / "input").is_dir()]
    for name in names:
        update_fixture(name)


if __name__ == "__main__":
    main()
