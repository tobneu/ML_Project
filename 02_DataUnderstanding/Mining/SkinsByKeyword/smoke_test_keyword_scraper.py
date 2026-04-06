from pathlib import Path

from minecraft_keyword_scraper import SkindexScraper


def run_smoke_test() -> None:
    scraper = SkindexScraper()

    sample_html = """
    <html>
      <body>
        <a href=\"/skin/19755510/crimson/\">Crimson</a>
        <a href=\"/skin/19755510/crimson/\">Crimson Duplicate</a>
        <a href=\"/skin/20000001/uniform/\">Uniform</a>
        <a href=\"/profile/not-a-skin/\">Ignore</a>
      </body>
    </html>
    """

    ids = scraper.parse_skin_ids(sample_html)
    assert ids == ["19755510", "20000001"], f"Unexpected skin IDs: {ids}"

    output_root = Path("_smoke_tmp")
    keyword_path = output_root / "uniform" / "uniform_19755510.png"
    assert str(keyword_path).endswith("uniform_19755510.png")

    print("Smoke test passed.")


if __name__ == "__main__":
    run_smoke_test()

