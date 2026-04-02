import base64
import json
import logging
import os
import time
from typing import Optional

import pandas as pd
import requests

HOST = "https://sessionserver.mojang.com/session/minecraft/profile/"
MANIFEST_COLUMNS = ["uuid", "skin_url", "image_path", "label"]


logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def extract_skin_url(mojang_api_response: dict) -> Optional[str]:
    """Extract the direct skin image URL from Mojang profile response."""
    properties = mojang_api_response.get("properties", [])

    for prop in properties:
        if prop.get("name") == "textures" and prop.get("value"):
            decoded_bytes = base64.b64decode(prop["value"])
            decoded_string = decoded_bytes.decode("utf-8")
            textures_data = json.loads(decoded_string)
            return textures_data.get("textures", {}).get("SKIN", {}).get("url")

    return None


def read_uuids_to_dataframe(
    uuid_list_path: str,
    image_directory: str,
    default_label: str = "unlabeled",
) -> pd.DataFrame:
    """Create a manifest DataFrame from UUID list with deterministic image paths."""
    logger.info("Reading UUIDs from %s", uuid_list_path)
    with open(uuid_list_path, "r", encoding="utf-8") as file:
        uuids = [line.strip() for line in file if line.strip()]
    input_count = len(uuids)

    # Preserve first-seen order and avoid duplicate work.
    uuids = list(dict.fromkeys(uuids))
    if len(uuids) != input_count:
        logger.info("Removed %d duplicate UUID rows", input_count - len(uuids))

    image_paths = [os.path.join(image_directory, f"{uuid}.png") for uuid in uuids]
    df = pd.DataFrame(
        {
            "uuid": uuids,
            "skin_url": pd.NA,
            "image_path": image_paths,
            "label": default_label,
        },
        columns=MANIFEST_COLUMNS,
    )
    logger.info("Prepared UUID DataFrame with %d rows", len(df))
    return df


def save_manifest(df: pd.DataFrame, manifest_path: str) -> None:
    """Persist the manifest in CSV format for resumable runs."""
    parent_dir = os.path.dirname(manifest_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    df.to_csv(manifest_path, index=False, encoding="utf-8")
    logger.info("Saved manifest with %d rows to %s", len(df), manifest_path)


def load_manifest(manifest_path: str) -> pd.DataFrame:
    """Load manifest CSV and normalize required columns."""
    df = pd.read_csv(manifest_path, dtype=str, keep_default_na=True)

    for column in MANIFEST_COLUMNS:
        if column not in df.columns:
            if column == "label":
                df[column] = "unlabeled"
            else:
                df[column] = pd.NA

    df = df[MANIFEST_COLUMNS]
    df["label"] = df["label"].fillna("unlabeled")
    logger.info("Loaded manifest with %d rows from %s", len(df), manifest_path)
    return df


def build_or_load_manifest(
    uuid_list_path: str,
    image_directory: str,
    manifest_path: str,
    default_label: str = "unlabeled",
) -> pd.DataFrame:
    """Create a new manifest or merge new UUIDs into existing one."""
    if os.path.exists(manifest_path):
        logger.info("Manifest exists, merging new UUIDs into %s", manifest_path)
        existing = load_manifest(manifest_path)
        incoming = read_uuids_to_dataframe(
            uuid_list_path=uuid_list_path,
            image_directory=image_directory,
            default_label=default_label,
        )

        merged = pd.concat([existing, incoming], ignore_index=True)
        merged = merged.drop_duplicates(subset=["uuid"], keep="first")
        merged = merged[MANIFEST_COLUMNS]
        logger.info(
            "Manifest merge complete: existing=%d incoming=%d merged=%d",
            len(existing),
            len(incoming),
            len(merged),
        )
        return merged

    logger.info("No manifest found. Creating new manifest from UUID list")
    return read_uuids_to_dataframe(
        uuid_list_path=uuid_list_path,
        image_directory=image_directory,
        default_label=default_label,
    )


def _get_json_with_retries(
    url: str,
    timeout_seconds: int,
    max_retries: int,
    retry_sleep_seconds: float,
) -> Optional[dict]:
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=timeout_seconds)

            if response.status_code == 429:
                wait_time = float(response.headers.get("Retry-After", retry_sleep_seconds))
                logger.warning("Rate limited on profile request. Waiting %.1fs", wait_time)
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            if attempt == max_retries:
                logger.warning("Profile request failed after %d attempts: %s", max_retries, error)
                return None
            logger.warning("Profile request attempt %d/%d failed: %s", attempt, max_retries, error)
            time.sleep(retry_sleep_seconds)

    return None


def _download_file_with_retries(
    file_url: str,
    destination_path: str,
    timeout_seconds: int,
    max_retries: int,
    retry_sleep_seconds: float,
) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(file_url, timeout=timeout_seconds)

            if response.status_code == 429:
                wait_time = float(response.headers.get("Retry-After", retry_sleep_seconds))
                logger.warning("Rate limited on skin download. Waiting %.1fs", wait_time)
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            with open(destination_path, "wb") as file:
                file.write(response.content)
            return True
        except requests.RequestException as error:
            if attempt == max_retries:
                logger.warning("Download failed after %d attempts for %s: %s", max_retries, destination_path, error)
                return False
            logger.warning("Download attempt %d/%d failed for %s: %s", attempt, max_retries, destination_path, error)
            time.sleep(retry_sleep_seconds)

    return False


def populate_skin_urls(
    df: pd.DataFrame,
    host: str = HOST,
    timeout_seconds: int = 15,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    save_every: int = 100,
    manifest_path: Optional[str] = None,
) -> pd.DataFrame:
    """Fill missing skin URLs only, so reruns are idempotent."""
    missing_url_indices = df.index[df["skin_url"].isna()].tolist()
    total_missing = len(missing_url_indices)
    if total_missing == 0:
        logger.info("URL stage: no missing skin URLs")
        return df

    logger.info("URL stage: resolving %d missing skin URLs", total_missing)
    resolved_count = 0
    no_skin_count = 0
    failed_count = 0

    for i, idx in enumerate(missing_url_indices, start=1):
        uuid = df.at[idx, "uuid"]
        profile = _get_json_with_retries(
            url=f"{host}{uuid}",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_sleep_seconds=retry_sleep_seconds,
        )

        if profile is None:
            failed_count += 1
            continue

        skin_url = extract_skin_url(profile)
        if skin_url:
            df.at[idx, "skin_url"] = skin_url
            resolved_count += 1
        else:
            no_skin_count += 1

        if manifest_path and save_every > 0 and i % save_every == 0:
            save_manifest(df, manifest_path)
            logger.info(
                "URL stage progress: %d/%d processed | resolved=%d no_skin=%d failed=%d",
                i,
                total_missing,
                resolved_count,
                no_skin_count,
                failed_count,
            )

    logger.info(
        "URL stage done: processed=%d resolved=%d no_skin=%d failed=%d",
        total_missing,
        resolved_count,
        no_skin_count,
        failed_count,
    )

    return df


def download_skins_from_dataframe(
    df: pd.DataFrame,
    timeout_seconds: int = 20,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    save_every: int = 100,
    manifest_path: Optional[str] = None,
) -> pd.DataFrame:
    """Download skins from DataFrame and skip files already present."""
    downloadable_indices = df.index[df["skin_url"].notna() & df["image_path"].notna()].tolist()
    total_candidates = len(downloadable_indices)
    if total_candidates == 0:
        logger.info("Download stage: no rows with skin_url + image_path")
        return df

    logger.info("Download stage: evaluating %d candidate rows", total_candidates)
    skipped_existing = 0
    downloaded_count = 0
    failed_count = 0

    for i, idx in enumerate(downloadable_indices, start=1):
        image_path = df.at[idx, "image_path"]
        if os.path.exists(image_path):
            skipped_existing += 1
            continue

        skin_url = df.at[idx, "skin_url"]
        success = _download_file_with_retries(
            file_url=skin_url,
            destination_path=image_path,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_sleep_seconds=retry_sleep_seconds,
        )
        if success:
            downloaded_count += 1
        else:
            failed_count += 1

        if manifest_path and save_every > 0 and i % save_every == 0:
            save_manifest(df, manifest_path)
            logger.info(
                "Download stage progress: %d/%d evaluated | downloaded=%d skipped=%d failed=%d",
                i,
                total_candidates,
                downloaded_count,
                skipped_existing,
                failed_count,
            )

    logger.info(
        "Download stage done: candidates=%d downloaded=%d skipped=%d failed=%d",
        total_candidates,
        downloaded_count,
        skipped_existing,
        failed_count,
    )

    return df


def run_pipeline(
    uuid_list_path: str,
    image_directory: str,
    manifest_path: str,
    default_label: str = "unlabeled",
    save_every: int = 100,
) -> pd.DataFrame:
    """Full idempotent pipeline: UUIDs -> skin URLs -> downloaded images."""
    logger.info("Pipeline start")
    df = build_or_load_manifest(
        uuid_list_path=uuid_list_path,
        image_directory=image_directory,
        manifest_path=manifest_path,
        default_label=default_label,
    )
    save_manifest(df, manifest_path)

    df = populate_skin_urls(df=df, save_every=save_every, manifest_path=manifest_path)
    save_manifest(df, manifest_path)

    df = download_skins_from_dataframe(df=df, save_every=save_every, manifest_path=manifest_path)
    save_manifest(df, manifest_path)
    logger.info("Pipeline done: total rows=%d", len(df))
    return df


def resume_from_manifest(
    manifest_path: str,
    save_every: int = 100,
    repopulate_missing_urls: bool = True,
) -> pd.DataFrame:
    """Resume processing from an existing manifest file."""
    logger.info("Resume start from %s", manifest_path)
    df = load_manifest(manifest_path)

    if repopulate_missing_urls:
        logger.info("Resume mode: repopulate missing URLs is enabled")
        df = populate_skin_urls(df=df, save_every=save_every, manifest_path=manifest_path)
        save_manifest(df, manifest_path)
    else:
        logger.info("Resume mode: skipping URL repopulation")

    df = download_skins_from_dataframe(df=df, save_every=save_every, manifest_path=manifest_path)
    save_manifest(df, manifest_path)
    logger.info("Resume done: total rows=%d", len(df))
    return df


if __name__ == "__main__":
    run_pipeline(
        uuid_list_path="../../../data/skins/general/uuid_list.txt",
        image_directory="../../data/skins/general/skins",
        manifest_path="../../../data/skins/general/skin_manifest.csv",
    )

