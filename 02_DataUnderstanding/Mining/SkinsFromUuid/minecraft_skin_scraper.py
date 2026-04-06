import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import time
from typing import Iterable, Optional

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


def _normalize_row_limits(total_rows: int, start_row: Optional[int], stop_row: Optional[int]) -> tuple[int, int]:
    """Normalize optional row window as a 0-based half-open range [start_row, stop_row)."""
    start = 0 if start_row is None else start_row
    stop = total_rows if stop_row is None else stop_row

    if start < 0:
        raise ValueError(f"start_row must be >= 0, got {start_row}")
    if stop < 0:
        raise ValueError(f"stop_row must be >= 0, got {stop_row}")
    if stop < start:
        raise ValueError(f"stop_row ({stop_row}) must be >= start_row ({start_row})")

    return min(start, total_rows), min(stop, total_rows)


def read_uuids(
    uuid_list_path: str,
    start_row: Optional[int] = None,
    stop_row: Optional[int] = None,
) -> list[str]:
    """Read UUID file, apply optional row limits, and de-duplicate while preserving first-seen order."""
    logger.info("Reading UUIDs from %s", uuid_list_path)
    with open(uuid_list_path, "r", encoding="utf-8") as file:
        uuids = [line.strip() for line in file if line.strip()]

    total_rows = len(uuids)
    start, stop = _normalize_row_limits(total_rows, start_row, stop_row)
    limited_uuids = uuids[start:stop]

    input_count = len(limited_uuids)
    limited_uuids = list(dict.fromkeys(limited_uuids))
    if len(limited_uuids) != input_count:
        logger.info("Removed %d duplicate UUID rows in selected range", input_count - len(limited_uuids))

    logger.info(
        "Selected UUID rows: start=%d stop=%d (exclusive), count=%d",
        start,
        stop,
        len(limited_uuids),
    )
    return limited_uuids


def _uuids_to_dataframe(
    uuids: list[str],
    image_directory: str,
    default_label: str = "unlabeled",
) -> pd.DataFrame:
    """Create a manifest DataFrame from UUIDs with deterministic image paths."""
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


def read_uuids_to_dataframe(
    uuid_list_path: str,
    image_directory: str,
    default_label: str = "unlabeled",
    start_row: Optional[int] = None,
    stop_row: Optional[int] = None,
) -> pd.DataFrame:
    """Create a manifest DataFrame from UUID list with deterministic image paths."""
    uuids = read_uuids(
        uuid_list_path=uuid_list_path,
        start_row=start_row,
        stop_row=stop_row,
    )
    return _uuids_to_dataframe(uuids=uuids, image_directory=image_directory, default_label=default_label)


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
    start_row: Optional[int] = None,
    stop_row: Optional[int] = None,
    selected_uuids: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Create a new manifest or merge new UUIDs into existing one."""
    if os.path.exists(manifest_path):
        logger.info("Manifest exists, merging new UUIDs into %s", manifest_path)
        existing = load_manifest(manifest_path)
        uuids_for_manifest = selected_uuids
        if uuids_for_manifest is None:
            uuids_for_manifest = read_uuids(
                uuid_list_path=uuid_list_path,
                start_row=start_row,
                stop_row=stop_row,
            )
        incoming = _uuids_to_dataframe(
            uuids=uuids_for_manifest,
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
        start_row=start_row,
        stop_row=stop_row,
    )


def _get_json_with_retries(
    url: str,
    timeout_seconds: int,
    max_retries: int,
    retry_sleep_seconds: float,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    request_get = session.get if session else requests.get
    for attempt in range(1, max_retries + 1):
        try:
            response = request_get(url, timeout=timeout_seconds)

            if response.status_code == 429:
                wait_time = float(response.headers.get("Retry-After", retry_sleep_seconds))
                logger.warning("Rate limited on profile request. Waiting %.1fs", wait_time)
                time.sleep(wait_time)
                continue

            if response.status_code in (204, 404):
                return {}

            if 400 <= response.status_code < 500:
                logger.warning("Client error on profile request (%d): %s", response.status_code, url)
                return None

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
    session: Optional[requests.Session] = None,
) -> bool:
    request_get = session.get if session else requests.get
    for attempt in range(1, max_retries + 1):
        try:
            response = request_get(file_url, timeout=timeout_seconds)

            if response.status_code == 429:
                wait_time = float(response.headers.get("Retry-After", retry_sleep_seconds))
                logger.warning("Rate limited on skin download. Waiting %.1fs", wait_time)
                time.sleep(wait_time)
                continue

            if 400 <= response.status_code < 500:
                logger.warning("Client error on skin download (%d): %s", response.status_code, file_url)
                return False

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


def _resolve_skin_url_for_uuid(
    uuid: str,
    host: str,
    timeout_seconds: int,
    max_retries: int,
    retry_sleep_seconds: float,
) -> tuple[Optional[str], str]:
    """Return (skin_url, status) where status is one of: resolved, no_skin, failed."""
    profile = _get_json_with_retries(
        url=f"{host}{uuid}",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_sleep_seconds=retry_sleep_seconds,
    )
    if profile is None:
        return None, "failed"

    skin_url = extract_skin_url(profile)
    if skin_url:
        return skin_url, "resolved"
    return None, "no_skin"


def _resolve_skin_urls_for_indices(
    df: pd.DataFrame,
    indices: Iterable[int],
    host: str = HOST,
    timeout_seconds: int = 15,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    max_workers: int = 8,
) -> tuple[int, int, int, list[int]]:
    """Resolve skin URLs for given DataFrame indices and return stage counters plus resolved indices."""
    index_list = list(indices)
    resolved_count = 0
    no_skin_count = 0
    failed_count = 0
    resolved_indices: list[int] = []

    if not index_list:
        return resolved_count, no_skin_count, failed_count, resolved_indices

    if max_workers <= 1 or len(index_list) == 1:
        for idx in index_list:
            uuid = df.at[idx, "uuid"]
            skin_url, status = _resolve_skin_url_for_uuid(
                uuid=uuid,
                host=host,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            if status == "resolved" and skin_url:
                df.at[idx, "skin_url"] = skin_url
                resolved_count += 1
                resolved_indices.append(idx)
            elif status == "no_skin":
                no_skin_count += 1
            else:
                failed_count += 1
        return resolved_count, no_skin_count, failed_count, resolved_indices

    worker_count = min(max_workers, len(index_list))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_idx = {
            executor.submit(
                _resolve_skin_url_for_uuid,
                df.at[idx, "uuid"],
                host,
                timeout_seconds,
                max_retries,
                retry_sleep_seconds,
            ): idx
            for idx in index_list
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                skin_url, status = future.result()
            except Exception as error:  # pragma: no cover - defensive handling for worker failures
                logger.warning("Worker failed while resolving UUID %s: %s", df.at[idx, "uuid"], error)
                failed_count += 1
                continue

            if status == "resolved" and skin_url:
                df.at[idx, "skin_url"] = skin_url
                resolved_count += 1
                resolved_indices.append(idx)
            elif status == "no_skin":
                no_skin_count += 1
            else:
                failed_count += 1

    return resolved_count, no_skin_count, failed_count, resolved_indices


def populate_skin_urls(
    df: pd.DataFrame,
    host: str = HOST,
    timeout_seconds: int = 15,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    save_every: int = 100,
    manifest_path: Optional[str] = None,
    row_indices: Optional[list[int]] = None,
    max_workers: int = 8,
) -> pd.DataFrame:
    """Fill missing skin URLs only, so reruns are idempotent."""
    if row_indices is None:
        candidate_indices = df.index.tolist()
    else:
        candidate_indices = row_indices

    missing_url_indices = [idx for idx in candidate_indices if pd.isna(df.at[idx, "skin_url"])]
    total_missing = len(missing_url_indices)
    if total_missing == 0:
        logger.info("URL stage: no missing skin URLs")
        return df

    logger.info("URL stage: resolving %d missing skin URLs", total_missing)
    resolved_count = 0
    no_skin_count = 0
    failed_count = 0

    batch_size = save_every if save_every > 0 else total_missing
    for batch_start in range(0, total_missing, batch_size):
        batch_indices = missing_url_indices[batch_start : batch_start + batch_size]
        batch_end = batch_start + len(batch_indices)

        batch_resolved, batch_no_skin, batch_failed, _ = _resolve_skin_urls_for_indices(
            df=df,
            indices=batch_indices,
            host=host,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_sleep_seconds=retry_sleep_seconds,
            max_workers=max_workers,
        )
        resolved_count += batch_resolved
        no_skin_count += batch_no_skin
        failed_count += batch_failed

        if manifest_path:
            save_manifest(df, manifest_path)
            logger.info(
                "URL stage progress: %d/%d processed | resolved=%d no_skin=%d failed=%d",
                batch_end,
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
    row_indices: Optional[list[int]] = None,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Download skins from DataFrame and skip files already present."""
    if row_indices is None:
        candidate_indices = df.index.tolist()
    else:
        candidate_indices = row_indices

    downloadable_indices = [
        idx for idx in candidate_indices if pd.notna(df.at[idx, "skin_url"]) and pd.notna(df.at[idx, "image_path"])
    ]
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
            session=session,
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
    start_row: Optional[int] = None,
    stop_row: Optional[int] = None,
    mojang_max_workers: int = 8,
) -> pd.DataFrame:
    """Full idempotent pipeline: UUIDs -> skin URLs -> downloaded images."""
    logger.info("Pipeline start")

    selected_uuids = read_uuids(
        uuid_list_path=uuid_list_path,
        start_row=start_row,
        stop_row=stop_row,
    )
    selected_uuid_set = set(selected_uuids)

    df = build_or_load_manifest(
        uuid_list_path=uuid_list_path,
        image_directory=image_directory,
        manifest_path=manifest_path,
        default_label=default_label,
        start_row=start_row,
        stop_row=stop_row,
        selected_uuids=selected_uuids,
    )
    save_manifest(df, manifest_path)

    target_indices = df.index[df["uuid"].isin(selected_uuid_set)].tolist()
    missing_url_indices = [idx for idx in target_indices if pd.isna(df.at[idx, "skin_url"])]
    total_missing = len(missing_url_indices)

    if total_missing > 0:
        logger.info("Pipeline URL batches: resolving %d missing skin URLs", total_missing)
        batch_size = save_every if save_every > 0 else total_missing
        resolved_count = 0
        no_skin_count = 0
        failed_count = 0

        for batch_start in range(0, total_missing, batch_size):
            batch_indices = missing_url_indices[batch_start : batch_start + batch_size]
            batch_end = batch_start + len(batch_indices)

            batch_resolved, batch_no_skin, batch_failed, _ = _resolve_skin_urls_for_indices(
                df=df,
                indices=batch_indices,
                max_workers=mojang_max_workers,
            )
            resolved_count += batch_resolved
            no_skin_count += batch_no_skin
            failed_count += batch_failed

            # Persist URL progress first, then download this same batch immediately.
            save_manifest(df, manifest_path)
            df = download_skins_from_dataframe(
                df=df,
                save_every=0,
                manifest_path=None,
                row_indices=batch_indices,
            )
            save_manifest(df, manifest_path)

            logger.info(
                "Pipeline batch progress: %d/%d URL rows processed | resolved=%d no_skin=%d failed=%d",
                batch_end,
                total_missing,
                resolved_count,
                no_skin_count,
                failed_count,
            )

    else:
        logger.info("Pipeline URL batches: no missing skin URLs in selected range")

    # Catch-up pass for rows that already had URLs but missing local image files.
    df = download_skins_from_dataframe(df=df, save_every=save_every, manifest_path=manifest_path, row_indices=target_indices)
    save_manifest(df, manifest_path)
    logger.info("Pipeline done: total rows=%d", len(df))
    return df


def resume_from_manifest(
    manifest_path: str,
    save_every: int = 100,
    repopulate_missing_urls: bool = True,
    uuid_list_path: Optional[str] = None,
    start_row: Optional[int] = None,
    stop_row: Optional[int] = None,
    mojang_max_workers: int = 8,
) -> pd.DataFrame:
    """Resume processing from an existing manifest file."""
    logger.info("Resume start from %s", manifest_path)
    df = load_manifest(manifest_path)

    target_indices: Optional[list[int]] = None
    if uuid_list_path is not None:
        selected_uuids = set(read_uuids(uuid_list_path, start_row=start_row, stop_row=stop_row))
        target_indices = df.index[df["uuid"].isin(selected_uuids)].tolist()
        logger.info("Resume mode: constrained to %d rows from uuid_list range", len(target_indices))

    if repopulate_missing_urls:
        logger.info("Resume mode: repopulate missing URLs is enabled")
        df = populate_skin_urls(
            df=df,
            save_every=save_every,
            manifest_path=manifest_path,
            row_indices=target_indices,
            max_workers=mojang_max_workers,
        )
        save_manifest(df, manifest_path)
    else:
        logger.info("Resume mode: skipping URL repopulation")

    df = download_skins_from_dataframe(
        df=df,
        save_every=save_every,
        manifest_path=manifest_path,
        row_indices=target_indices,
    )
    save_manifest(df, manifest_path)
    logger.info("Resume done: total rows=%d", len(df))
    return df


if __name__ == "__main__":
    run_pipeline(
        uuid_list_path="../../../data/skins/general/uuid_list.txt",
        image_directory="../../data/skins/general/skins",
        manifest_path="../../../data/skins/general/skin_manifest.csv",
    )

