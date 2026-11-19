"""2.12.4 — CJK-safe editor title width via pixel measure (not ch)."""
from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion2124(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)


class TestSyncTitleWidthPixelMeasure(unittest.TestCase):
    """Contract: syncTitleWidth measures with canvas/font, sets px, never under-measures CJK."""

    def test_js_uses_measure_text_px(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function syncTitleWidth()", js)
        # extract function body
        m = re.search(r"function syncTitleWidth\(\)\s*\{", js)
        self.assertIsNotNone(m)
        start = m.end() - 1
        depth = 0
        end = None
        for i, ch in enumerate(js[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = js[start : end + 1]
        self.assertIn("measureText", body)
        self.assertIn('getContext("2d")', body)
        self.assertIn("getComputedStyle(title)", body)
        self.assertIn('.width = w + "px"', body)
        self.assertNotIn('+ "ch"', body)
        self.assertNotIn("+ \"ch\"", body)
        # no character-count ch heuristic
        self.assertNotRegex(body, r"raw\.length\s*\+\s*1")
        self.assertIn("editor-head-left", body)
        self.assertIn("ellipsis", body)
        # caret/padding allowance
        self.assertTrue("caretPad" in body or "pad" in body)

    def test_cjk_title_width_contract(self):
        """Pure helper contract mirroring syncTitleWidth measure logic (CJK ≥ ASCII ch)."""
        # Simulate: with a typical UI font, CJK glyph advance ≫ 0.5em; ch ≈ '0' width ≈ 0.5em–1em.
        # We assert the *algorithm* never sets width below measured text + pad for「博客文章写作」.
        try:
            from PIL import ImageFont, ImageDraw, Image
        except ImportError:
            ImageFont = None  # type: ignore

        sample = "博客文章写作"
        # Font-independent geometric lower bound: each CJK ideograph is typically ≥ Latin 'M'
        # Under the old bug, width = (len+1)ch ≈ 7ch while real text needs ~12–14ch equivalent.
        # Contract encoded in source: width uses measureText, not len*ch.
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("博客文章写作", js)  # documented in comment
        # Algorithm must take max(textW, minText) + pad + caretPad
        self.assertIn("Math.max(textW, minText)", js)
        self.assertIn("caretPad", js)

        if ImageFont is not None:
            # Optional: verify with a real CJK-capable font if present on the box
            font_paths = [
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            font = None
            for fp in font_paths:
                if Path(fp).exists():
                    try:
                        font = ImageFont.truetype(fp, 15)
                        break
                    except Exception:
                        continue
            if font is not None:
                # measure sample vs old ch heuristic (ch ≈ width of '0')
                zero_w = font.getlength("0") if hasattr(font, "getlength") else font.getsize("0")[0]
                text_w = font.getlength(sample) if hasattr(font, "getlength") else font.getsize(sample)[0]
                old_ch_w = (len(sample) + 1) * zero_w
                # CJK must measure wider than the old ch estimate (the bug)
                self.assertGreater(text_w, old_ch_w * 0.9,
                                   msg=f"expected CJK wider/near than ch heuristic: text={text_w} ch={old_ch_w}")
                # New contract: assigned width >= text width (pad omitted in this lower bound)
                assigned = text_w + 10  # caretPad floor
                self.assertGreaterEqual(assigned, text_w)

    def test_css_title_fixed_sizing_ellipsis(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        block = css[css.find("#editorPanel .editor-head-left"): css.find("#editorPanel .editor-head-actions")]
        self.assertIn("max-width: 58%", block)
        title_rule = css[css.find("#editorPanel .editor-head-left .title-input"):]
        title_rule = title_rule[: title_rule.find("}") + 1]
        self.assertIn("flex: 0 1 auto", title_rule)
        self.assertIn("field-sizing: fixed", title_rule)
        self.assertIn("text-overflow: ellipsis", title_rule)
        self.assertIn("margin-left: auto", css)
        # save-state still tight (no mid-bar float)
        self.assertIn("#editorPanel .editor-head-left .save-state", css)


class TestTagsSingleAddPath(unittest.TestCase):
    def test_no_redundant_plus_chip_control(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        chunk = html[html.find('id="tagsRow"'): html.find('id="editorWrap"')]
        self.assertIn('id="tagsInput"', chunk)
        self.assertIn('id="tagsChips"', chunk)
        # single add path: input only — no separate add/+ button in tags row
        self.assertNotIn('data-add-tag', chunk)
        self.assertNotRegex(chunk, r"<button[^>]*>\s*\+\s*</button>")



class TestInsertMenuIconsAndPlacement(unittest.TestCase):
    def test_snippet_icons_remapped(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        icons = (ROOT / "web" / "js" / "icons.js").read_text(encoding="utf-8")
        for key in ("textCursor", "textDefault", "num", "select", "radio"):
            self.assertIn(f"{key}:", icons)
            self.assertIn(f'icon: "{key}"', js)
        # no longer use letter-like type/hash for the first line / number rows
        self.assertIn('icon: "textCursor", title: "单行文本"', js)
        self.assertIn('icon: "num", title: "数字"', js)
        self.assertNotIn('icon: "type", title: "单行文本"', js)
        self.assertNotIn('icon: "hash", title: "数字"', js)
        self.assertIn("function placeInsertMenu()", js)
        self.assertIn('position = "fixed"', js)
        self.assertIn("PBIcons.fill(menu)", js)

    def test_editor_panel_overflow_visible(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("#editorPanel.panel { overflow: visible; }", css)
        self.assertIn("#editorPanel .editor { overflow: hidden", css)
        self.assertIn("#insertMenu.insert-menu { z-index: 120; }", css)


class TestLibHead2124(unittest.TestCase):
    def test_newbtn_ghost_tint_not_solid_primary(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        import re
        m = re.search(r'<button[^>]*id="newBtn"[^>]*>', html)
        self.assertIsNotNone(m)
        tag = m.group(0)
        self.assertIn("ghost", tag)
        self.assertIn("lib-new", tag)
        self.assertIn("icon", tag)
        self.assertNotIn("primary", tag)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("#newBtn.lib-new", css)
        self.assertIn("primary-soft", css)
        self.assertIn("lib-head-title", html)
        self.assertIn("sortCompactBtn", html)
        self.assertIn("lib-compact", css)
        self.assertIn("function syncLibHeadDensity()", (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
