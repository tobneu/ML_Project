# Keyword Skin Scraper

This module scrapes Minecraft skins from `minecraftskins.com` by keyword.

## Highlights

- Uses `cloudscraper` for Cloudflare-protected search pages.
- Parses skin IDs from URLs like `/skin/<id>/...`.
- Downloads PNGs through direct endpoint `/skin/download/<id>`.
- Supports retry handling for HTTP `403`/`429` with constant backoff.
- Stops when `target_count` images are available.

## Files

- `minecraft_keyword_scraper.py`: main scraper implementation.
- `smoke_test_keyword_scraper.py`: quick parser smoke test.

## Quick Start

Run from `02_DataUnderstanding/Mining/SkinsByKeyword`:

```powershell
python .\smoke_test_keyword_scraper.py
python .\minecraft_keyword_scraper.py
```

Example programmatic use:

```python
from minecraft_keyword_scraper import run

paths = run(keyword="uniform", target_count=25)
print(f"Downloaded {len(paths)} files")
```

