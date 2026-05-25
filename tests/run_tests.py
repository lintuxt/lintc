#!/usr/bin/env python3
"""Entry point: discover and run every test in tools/lintc-tests/test_*.py."""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(THIS_DIR), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
