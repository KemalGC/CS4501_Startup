"""Tests-first accessible styling contract for the offline local HTML shell.

No browser, pose network, live LLM, or real footage is used here.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strokesense.web import _document


class LocalPageDesignTests(unittest.TestCase):
    def test_semantic_navigation_and_skip_link_preserve_escaped_title(self):
        page = _document("<unsafe> & title", "<p>Example content</p>").decode("utf-8")
        self.assertIn('<a class="skip-link" href="#content">Skip to content</a>', page)
        self.assertIn('<nav aria-label="Primary navigation">', page)
        self.assertIn('href="/#upload-clip"', page)
        self.assertIn('href="/#recent-analyses"', page)
        self.assertIn('<main id="content"', page)
        self.assertIn("&lt;unsafe&gt; &amp; title", page)
        self.assertNotIn("<unsafe>", page)
        self.assertIn("<p>Example content</p>", page)

    def test_responsive_keyboard_accessible_visual_treatment_without_external_assets(self):
        page = _document("StrokeSense", "<form><input type='file'></form>").decode()
        self.assertIn("@media (max-width: 720px)", page)
        self.assertIn(":focus-visible", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertIn('input[type="file"]', page)
        self.assertIn("color-scheme:", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<link rel=\"stylesheet\"", page)

    def test_auto_refresh_remains_available_on_running_job_page(self):
        page = _document("Analysis status", "<p>Queued</p>", refresh=True).decode()
        self.assertIn('<meta http-equiv="refresh" content="2">', page)
        self.assertIn("Queued", page)


if __name__ == "__main__":
    unittest.main()
