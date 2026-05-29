"""lintc-swiper — build-time plugin: inline image carousel.

Registers the `{{< lintc-swiper >}}` shortcode (partial: swiper_assets/
component.html) and ships a from-scratch, zero-dependency carousel
(swiper_assets/lintc-swiper.{js,css}) into dist/ on pages that use it.
No third-party engine. See internal-docs lintc v0.6 spec.
"""
from pathlib import Path

_HERE = Path(__file__).resolve().parent / "swiper_assets"

SHORTCODE = "lintc-swiper"
PARTIAL = _HERE / "component.html"
ASSETS = [
    _HERE / "lintc-swiper.css",
    _HERE / "lintc-swiper.js",
]
