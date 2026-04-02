# KeywordScraper

Simple, resumable scraper for `minecraftskins.com` keyword search pages.

## What it does

- Reads search pages (with fallback):
  - `https://www.minecraftskins.com/search/mostvotedskin/[keyword]/[pageIndex]/`
  - `https://www.minecraftskins.com/search/skin/[keyword]/[pageIndex]/`
- Extracts skin detail URLs from each search page
- Opens each detail URL and finds `img.skin-previews-wrapper`
- Downloads the PNG to `output_root/[keyword]/[keyword]_[index].png`
- Tracks progress in `output_root/[keyword]/progress.csv`

## Behavior

- Idempotent: reruns skip already successful rows
- Retries each request up to `2` reattempts (`3` total attempts)
- Uses a persistent HTTP session with browser-like headers for more reliable requests
- Optional: pass a raw browser `Cookie` header and extra headers from DevTools if the site blocks plain requests
- Stops with an error after `10` consecutive failed requests
- Stops pagination when target skin count is reached or no new skins are available

## Quick run

Use the notebook example in `02_DataUnderstanding/DataUnderstanding.ipynb` to import `KeywordScraper`, then pass your browser cookie header if the site returns `403`.

## Progress CSV columns

- `index`
- `keyword`
- `detail_url`
- `image_url`
- `file_path`
- `status` (`pending`, `failed`, `success`)
- `attempts`
- `last_error`
- `updated_at`

