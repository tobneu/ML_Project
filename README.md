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

## Keyword scraper for bad-class seed data

The Cloudflare-aware keyword scraper lives in `02_DataUnderstanding/Mining/SkinsByKeyword/minecraft_keyword_scraper.py`.

- Search pages are fetched via `cloudscraper`.
- Skin IDs are parsed from `/skin/<id>/...` links.
- PNGs are downloaded through `https://www.minecraftskins.com/skin/download/<id>`.
- Output is written to `data/skins/bad/<keyword>/<keyword>_<id>.png`.

Use `02_DataUnderstanding/DataUnderstanding.ipynb` to configure `keyword` and `target_count` and execute the scrape.

# Some basic toughts, to be moved to the correct subfolder in the end

## Some details

A Minecraft skin is a 64x64 png (jpg is not used due to transparency). Official description: https://minecraft.wiki/w/Skin
The image has several subsegments for head, body, both arms and legs. And addtional layer information. One part is 16x16 (except body). In difference to a standard image classification the positions within the image are fixed, so the features shoule be learned faster. Using the whole image at once is one solution, it would be possible to train the overlay extra or to train each region seperatly (region based CNN).

As measurement recall is more important than precision, a false negative is worse than a false positive

A big issue will be the inbalanced training set. Possible overcomes are BCEWithLogitsLoss (where rebalancing can be applied), using Focal Loss (FL(p_t) = - α (1 - p_t)^γ log(p_t) with for instance gamma = 2 and alpha = 0.75–0.95)

One possible solution can be using a custom threshold <> 0.5 for the prediction "banned / not banned". After finishing training the validation is run with different setting of the threshold for classification.

For Dataloading the exists methods like class torch.utils.data.WeightedRandomSampler

For the necessary data augmentation: The "usual" shifting, flipping or colour changing does not work. Alternatively color jittering and / or adding noise can be used. Usual this is done on the fly not during preprocessing. And of course only for training, not for validation or test.