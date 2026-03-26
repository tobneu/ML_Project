# ML Project

## Minecraft skin manifest pipeline

The skin scraping logic lives in `02_DataUnderstanding/Mining/minecraft_skin_scraper.py`.

It builds and persists a resumable CSV manifest with these columns:

- `uuid`
- `skin_url`
- `image_path`
- `label` (default: `unlabeled`)

### Pipeline behavior

- Uses separate paths for image files and manifest CSV.
- Fills missing `skin_url` values from Mojang API.
- Downloads images only when the target file does not exist yet.
- Safe to rerun after interruptions/rate limits (idempotent by design).

### Notebook entry point

Use `02_DataUnderstanding/Mining/MinecraftSkinScraper.ipynb` to run:

- `run_pipeline(...)` for a full run.
- `resume_from_manifest(...)` to continue from an existing CSV.

