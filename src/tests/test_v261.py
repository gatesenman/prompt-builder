"""2.6.1: every page a window loads must resolve from the bundle and load in WebView2.

2.6.0 shipped `index.html?theme=system`; WebView2 percent-encodes '?' in file:// URLs, so the
installed app requested 'index.html%3Ftheme=system' and showed ERR_FILE_NOT_FOUND."""
import os, re, sys, tempfile, unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))
import paths  # noqa: E402

WEB = SRC.parent / "web"


class PageUrls(unittest.TestCase):
    def test_urls_are_plain_existing_file_urls(self):
        for page in paths.PAGES:
            url = paths.page_url(page)
            self.assertTrue(url.startswith("file://"), url)
            self.assertNotIn("?", url)
            self.assertNotIn("#", url)
            self.assertTrue(paths.page_path(page).is_file())

    def test_independent_of_cwd(self):
        before = {k: paths.page_url(k) for k in paths.PAGES}
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                self.assertEqual(before, {k: paths.page_url(k) for k in paths.PAGES})
            finally:
                os.chdir(old)

    def test_pages_cover_every_html(self):
        self.assertEqual(sorted(paths.PAGES.values()), sorted(p.name for p in WEB.glob("*.html")))

    def test_referenced_assets_exist(self):
        self.assertEqual({k: [] for k in paths.PAGES}, paths.all_web_refs())
        for name in paths.PAGES.values():
            refs = re.findall(r'(?:href|src)="((?:css|js)/[^"]+)"', (WEB / name).read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(refs), 2, name)

    def test_missing_page_fails_closed(self):
        orig = paths.web_dir
        with tempfile.TemporaryDirectory() as d:
            paths.web_dir = lambda: Path(d)
            try:
                with self.assertRaises(paths.PageMissing) as cm:
                    paths.page_url("main")
                self.assertIn("index.html", str(cm.exception))
            finally:
                paths.web_dir = orig


class NoQueryStrings(unittest.TestCase):
    def test_app_windows_use_page_urls_only(self):
        src = (SRC / "app.py").read_text(encoding="utf-8")
        urls = re.findall(r"create_window\([^)]*?url=([^,]+),", src, re.S)
        self.assertEqual(len(urls), 2, urls)
        for u in urls:
            self.assertRegex(u.strip(), r'^self\.page_urls\["(main|quick)"\]$')
        self.assertNotIn("?theme", src)
        self.assertNotIn(".as_uri() +", src)

    def test_pages_do_not_depend_on_location_search(self):
        for page, name in paths.PAGES.items():
            html = (WEB / name).read_text(encoding="utf-8")
            self.assertNotIn("location.search", html)
            self.assertIn(f'window.__pbPage = "{page}"', html)
        for js in ("app.js", "quick.js"):
            self.assertNotIn("location.search", (WEB / "js" / js).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
