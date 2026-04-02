import unittest
from unittest.mock import MagicMock

from minecraftskins_com_scraper import BASE_URL, KeywordScraper


class KeywordScraperParsingTests(unittest.TestCase):
    def test_session_includes_browser_cookie_and_extra_headers(self):
        scraper = KeywordScraper(
            output_root="tmp",
            browser_cookie_header="cf_clearance=test-cookie; PHPSESSID=test-session",
            browser_extra_headers={"sec-ch-ua": '"Chromium";v="146"', "DNT": "1"},
        )

        self.assertEqual(scraper.session.headers.get("Cookie"), "cf_clearance=test-cookie; PHPSESSID=test-session")
        self.assertEqual(scraper.session.headers.get("sec-ch-ua"), '"Chromium";v="146"')
        self.assertEqual(scraper.session.headers.get("DNT"), "1")

    def test_get_response_uses_session_headers_and_referer_override(self):
        scraper = KeywordScraper(
            output_root="tmp",
            browser_cookie_header="cf_clearance=test-cookie",
            browser_extra_headers={"sec-ch-ua-mobile": "?0"},
        )
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.status_code = 200
        scraper.session.get = MagicMock(return_value=response)

        scraper._get_response("https://example.com/path", referer="https://example.com/ref")

        _, kwargs = scraper.session.get.call_args
        self.assertEqual(kwargs["headers"]["Cookie"], "cf_clearance=test-cookie")
        self.assertEqual(kwargs["headers"]["sec-ch-ua-mobile"], "?0")
        self.assertEqual(kwargs["headers"]["Referer"], "https://example.com/ref")

    def test_build_search_urls_contains_fallback_variants(self):
        scraper = KeywordScraper(output_root="tmp")
        urls = scraper._build_search_urls(keyword="zombie", page_index=1)
        self.assertEqual(
            urls,
            [
                f"{BASE_URL}/search/mostvotedskin/zombie/1/",
                f"{BASE_URL}/search/skin/zombie/1/",
            ],
        )

    def test_fetch_search_page_detail_urls_falls_back_to_second_variant(self):
        scraper = KeywordScraper(output_root="tmp")
        response = MagicMock()
        response.text = "<a href='/skin/123/test-skin/'>Skin</a>"

        scraper._get_response = MagicMock(side_effect=[None, response])

        detail_urls, used_url = scraper._fetch_search_page_detail_urls(keyword="zombie", page_index=1)

        self.assertEqual(detail_urls, [f"{BASE_URL}/skin/123/test-skin/"])
        self.assertEqual(used_url, f"{BASE_URL}/search/skin/zombie/1/")

    def test_fetch_search_page_detail_urls_returns_none_when_all_variants_fail(self):
        scraper = KeywordScraper(output_root="tmp")
        scraper._get_response = MagicMock(return_value=None)

        detail_urls, used_url = scraper._fetch_search_page_detail_urls(keyword="zombie", page_index=1)

        self.assertIsNone(detail_urls)
        self.assertIsNone(used_url)

    def test_extract_detail_urls_from_search_html(self):
        html = """
        <html>
          <body>
            <a href="/skin/23965476/miles-morales/">Miles</a>
            <a href="/skin/23965476/miles-morales/">Duplicate</a>
            <a href="/profile/some-user/">Profile</a>
          </body>
        </html>
        """
        urls = KeywordScraper._extract_detail_urls_from_search_html(html)
        self.assertEqual(urls, [f"{BASE_URL}/skin/23965476/miles-morales/"])

    def test_extract_preview_png_url_from_detail_html(self):
        html = """
        <html>
          <body>
            <img class="skin-previews-wrapper" src="/uploads/skins/2026/04/02/miles-morales-23965476.png?v950" />
          </body>
        </html>
        """
        image_url = KeywordScraper._extract_preview_png_url_from_detail_html(html)
        self.assertEqual(
            image_url,
            f"{BASE_URL}/uploads/skins/2026/04/02/miles-morales-23965476.png?v950",
        )

    def test_extract_preview_png_url_from_detail_html_returns_none_when_missing(self):
        html = "<html><body><img class='other-class' src='/uploads/skins/a.png'></body></html>"
        image_url = KeywordScraper._extract_preview_png_url_from_detail_html(html)
        self.assertIsNone(image_url)


if __name__ == "__main__":
    unittest.main()

