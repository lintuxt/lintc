"""Tests for the build-time plugin mechanism (config, discovery, emission)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lintc


class TestBuildConfig(unittest.TestCase):
    def test_build_plugins_default_empty(self):
        out = lintc._normalize_build_config(None)
        self.assertEqual(out, {"plugins": {}})

    def test_build_plugins_passthrough(self):
        out = lintc._normalize_build_config({"plugins": {"lintc-swiper": {}}})
        self.assertEqual(out["plugins"], {"lintc-swiper": {}})

    def test_build_plugins_wrong_type_raises(self):
        with self.assertRaises(lintc.BuildError):
            lintc._normalize_build_config({"plugins": ["not-a-mapping"]})


if __name__ == "__main__":
    unittest.main()
