import csv
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urldefrag, urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.minecraftskins.com"
SCRAPER_VERSION = "2026-04-02"
SEARCH_URL_TEMPLATES = [
    BASE_URL + "/search/mostvotedskin/{keyword}/{page_index}/",
    BASE_URL + "/search/skin/{keyword}/{page_index}/",
]
PROGRESS_FILE_NAME = "progress.csv"
PROGRESS_COLUMNS = [
    "index",
    "keyword",
    "detail_url",
    "image_url",
    "file_path",
    "status",
    "attempts",
    "last_error",
    "updated_at",
]


logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class KeywordScraper:
    def __init__(
        self,
        output_root: str,
        timeout_seconds: int = 20,
        retry_sleep_seconds: float = 1.0,
        request_reattempts: int = 2,
        max_consecutive_failed_requests: int = 10,
    ) -> None:
        self.output_root = output_root
        self.timeout_seconds = timeout_seconds
        self.retry_sleep_seconds = retry_sleep_seconds
        self.request_reattempts = request_reattempts
        self.max_consecutive_failed_requests = max_consecutive_failed_requests
        self.max_request_attempts = self.request_reattempts + 1
        self.consecutive_failed_requests = 0
        self.session = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
        self.default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Referer": BASE_URL + "/",
        }
        self.session.headers.update(self.default_headers)

    @staticmethod
    def _canonicalize_detail_url(url: str) -> str:
        # Strip fragments like #comments so one skin maps to one canonical detail URL.
        clean_url, _ = urldefrag(url)
        return clean_url

    @staticmethod
    def _sanitize_keyword(keyword: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "_", keyword.strip().lower())
        return sanitized.strip("_") or "keyword"

    def _count_rows_with_remaining_attempts(self, rows: List[Dict[str, str]]) -> int:
        remaining = 0
        for row in rows:
            if row.get("status") == "success":
                continue
            try:
                attempts = int(row.get("attempts", "0") or "0")
            except ValueError:
                attempts = 0
            if attempts < self.max_request_attempts:
                remaining += 1
        return remaining

    def _keyword_dir(self, keyword: str) -> str:
        return os.path.join(self.output_root, self._sanitize_keyword(keyword))

    def _progress_path(self, keyword: str) -> str:
        return os.path.join(self._keyword_dir(keyword), PROGRESS_FILE_NAME)

    def _build_search_urls(self, keyword: str, page_index: int) -> List[str]:
        return [
            template.format(keyword=keyword, page_index=page_index)
            for template in SEARCH_URL_TEMPLATES
        ]

    def _record_request_failure(self, error_message: str) -> None:
        self.consecutive_failed_requests += 1
        logger.warning(
            "Request failed (%d/%d): %s",
            self.consecutive_failed_requests,
            self.max_consecutive_failed_requests,
            error_message,
        )
        if self.consecutive_failed_requests >= self.max_consecutive_failed_requests:
            raise RuntimeError(
                "Stopping scraper: reached 10 consecutive failed requests in a row."
            )

    def _record_request_success(self) -> None:
        if self.consecutive_failed_requests:
            logger.info("Recovered after %d consecutive request failures", self.consecutive_failed_requests)
        self.consecutive_failed_requests = 0

    def _get_response(self, url: str, referer: Optional[str] = None) -> Optional[requests.Response]:
        headers = dict(self.session.headers)
        if referer:
            headers["Referer"] = referer

        for attempt in range(1, self.max_request_attempts + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds, headers=headers)

                if response.status_code in (403, 429):
                    raise requests.HTTPError(
                        f"{response.status_code} Client Error: blocked for url: {url}",
                        response=response,
                    )

                response.raise_for_status()
                self._record_request_success()
                return response
            except requests.RequestException as error:
                self._record_request_failure(f"{url} | attempt {attempt}/{self.max_request_attempts} | {error}")
                if attempt == self.max_request_attempts:
                    return None
                backoff_seconds = self.retry_sleep_seconds * attempt + random.uniform(0.1, 0.4)
                time.sleep(backoff_seconds)
        return None

    @staticmethod
    def _extract_detail_urls_from_search_html(html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        detail_urls: List[str] = []
        seen: set = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            if not href:
                continue
            if not re.match(r"^/skin/\d+", href):
                continue

            absolute_url = KeywordScraper._canonicalize_detail_url(urljoin(BASE_URL, href))
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            detail_urls.append(absolute_url)

        return detail_urls

    @staticmethod
    def _extract_preview_png_url_from_detail_html(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        # Prefer the explicit image-link input field when present on detail pages.
        image_link_input = soup.select_one("input#image-link-code")
        if image_link_input:
            input_value = image_link_input.get("value", "")
            if input_value:
                absolute_url = urljoin(BASE_URL, input_value)
                if ".png" in absolute_url.lower():
                    return absolute_url

        image = soup.select_one("img.skin-previews-wrapper")
        if not image:
            return None

        src = image.get("src")
        if not src:
            return None

        absolute_url = urljoin(BASE_URL, src)
        if ".png" not in absolute_url.lower():
            return None

        return absolute_url

    def _fetch_search_page_detail_urls(self, keyword: str, page_index: int) -> Tuple[Optional[List[str]], Optional[str]]:
        for search_url in self._build_search_urls(keyword=keyword, page_index=page_index):
            logger.info("Fetching search page keyword='%s' page=%d url=%s", keyword, page_index, search_url)
            response = self._get_response(search_url, referer=BASE_URL + "/")
            if response is None:
                continue
            detail_urls = self._extract_detail_urls_from_search_html(response.text)
            logger.info(
                "Search page parsed keyword='%s' page=%d detail_urls=%d",
                keyword,
                page_index,
                len(detail_urls),
            )
            return detail_urls, search_url

        return None, None

    def _fetch_preview_png_url(self, detail_url: str) -> Optional[str]:
        logger.debug("Fetching detail page: %s", detail_url)
        response = self._get_response(detail_url)
        if response is None:
            return None
        return self._extract_preview_png_url_from_detail_html(response.text)

    def _download_png(self, image_url: str, destination_path: str) -> bool:
        logger.debug("Downloading image %s -> %s", image_url, destination_path)
        response = self._get_response(image_url)
        if response is None:
            return False

        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        with open(destination_path, "wb") as file:
            file.write(response.content)
        return True

    def _load_progress(self, keyword: str) -> List[Dict[str, str]]:
        progress_path = self._progress_path(keyword)
        if not os.path.exists(progress_path):
            return []

        rows: List[Dict[str, str]] = []
        with open(progress_path, "r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                normalized = {column: row.get(column, "") for column in PROGRESS_COLUMNS}
                rows.append(normalized)
        return rows

    def _save_progress(self, keyword: str, rows: List[Dict[str, str]]) -> None:
        keyword_dir = self._keyword_dir(keyword)
        os.makedirs(keyword_dir, exist_ok=True)
        progress_path = self._progress_path(keyword)
        with open(progress_path, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=PROGRESS_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _count_success(rows: List[Dict[str, str]]) -> int:
        return sum(1 for row in rows if row.get("status") == "success")

    def scrape_keyword(self, keyword: str, target_count: int) -> List[Dict[str, str]]:
        if target_count <= 0:
            raise ValueError("target_count must be greater than 0")

        logger.info("KeywordScraper version=%s templates=%s", SCRAPER_VERSION, SEARCH_URL_TEMPLATES)

        keyword_clean = self._sanitize_keyword(keyword)
        keyword_dir = self._keyword_dir(keyword_clean)
        os.makedirs(keyword_dir, exist_ok=True)

        rows = self._load_progress(keyword_clean)
        logger.info(
            "Starting scrape keyword='%s' target=%d existing_rows=%d",
            keyword_clean,
            target_count,
            len(rows),
        )
        by_detail_url: Dict[str, Dict[str, str]] = {}
        max_index = 0

        for row in rows:
            detail_url = self._canonicalize_detail_url(row.get("detail_url", ""))
            if detail_url:
                row["detail_url"] = detail_url
                by_detail_url[detail_url] = row
            try:
                max_index = max(max_index, int(row.get("index", "0") or "0"))
            except ValueError:
                pass

        # Reconcile stale "success" rows where file was removed manually.
        reconciled_missing_files = 0
        for row in rows:
            if row.get("status") == "success" and row.get("file_path") and not os.path.exists(row["file_path"]):
                row["status"] = "pending"
                row["last_error"] = "file_missing_on_disk"
                row["updated_at"] = self._now_iso()
                reconciled_missing_files += 1

        if reconciled_missing_files:
            logger.warning(
                "Reconciled %d success rows with missing files for keyword '%s'",
                reconciled_missing_files,
                keyword_clean,
            )

        page_index = 1
        success_count = self._count_success(rows)
        consecutive_no_new_pages = 0
        last_page_signature: Optional[Tuple[str, ...]] = None

        while success_count < target_count:
            remaining_retryable_rows = self._count_rows_with_remaining_attempts(rows)
            if success_count + remaining_retryable_rows >= target_count:
                logger.info(
                    "Collected enough candidate rows for '%s' (success=%d retryable=%d target=%d), stopping pagination",
                    keyword_clean,
                    success_count,
                    remaining_retryable_rows,
                    target_count,
                )
                break

            page_detail_urls, used_search_url = self._fetch_search_page_detail_urls(keyword_clean, page_index)
            if page_detail_urls is None:
                logger.error(
                    "Search request failed for keyword '%s' at page %d across all search URL variants",
                    keyword_clean,
                    page_index,
                )
                break

            if not page_detail_urls:
                logger.info(
                    "No further skins available for keyword '%s' at page %d (url=%s)",
                    keyword_clean,
                    page_index,
                    used_search_url,
                )
                break

            page_signature = tuple(page_detail_urls)
            if last_page_signature is not None and page_signature == last_page_signature:
                logger.info(
                    "Detected repeated search page for keyword '%s' at page %d; stopping pagination",
                    keyword_clean,
                    page_index,
                )
                break
            last_page_signature = page_signature

            new_urls = [self._canonicalize_detail_url(url) for url in page_detail_urls if self._canonicalize_detail_url(url) not in by_detail_url]
            logger.info(
                "Page %d results for '%s': total=%d new=%d",
                page_index,
                keyword_clean,
                len(page_detail_urls),
                len(new_urls),
            )
            if not new_urls:
                consecutive_no_new_pages += 1
                logger.info(
                    "No new detail URLs on page %d for '%s' (%d/2)",
                    page_index,
                    keyword_clean,
                    consecutive_no_new_pages,
                )
                if consecutive_no_new_pages >= 2:
                    logger.info(
                        "Stopping pagination for '%s' after consecutive pages without new URLs",
                        keyword_clean,
                    )
                    break
                page_index += 1
                continue
            consecutive_no_new_pages = 0

            for detail_url in new_urls:
                remaining_retryable_rows = self._count_rows_with_remaining_attempts(rows)
                if success_count + remaining_retryable_rows >= target_count:
                    break

                max_index += 1
                file_name = f"{keyword_clean}_{max_index}.png"
                file_path = os.path.join(keyword_dir, file_name)
                row = {
                    "index": str(max_index),
                    "keyword": keyword_clean,
                    "detail_url": detail_url,
                    "image_url": "",
                    "file_path": file_path,
                    "status": "pending",
                    "attempts": "0",
                    "last_error": "",
                    "updated_at": self._now_iso(),
                }
                rows.append(row)
                by_detail_url[detail_url] = row
                logger.debug("Queued detail URL #%d for '%s': %s", max_index, keyword_clean, detail_url)

            self._save_progress(keyword_clean, rows)
            page_index += 1

        for row in rows:
            if success_count >= target_count:
                break

            if row.get("status") == "success":
                continue

            attempts = int(row.get("attempts", "0") or "0")
            if attempts >= self.max_request_attempts:
                logger.warning(
                    "Skipping row index=%s for '%s': max attempts reached (%d)",
                    row.get("index", "?"),
                    keyword_clean,
                    attempts,
                )
                continue

            while attempts < self.max_request_attempts:
                attempts += 1
                row["attempts"] = str(attempts)
                row["updated_at"] = self._now_iso()
                logger.info(
                    "Processing row index=%s keyword='%s' attempt=%d/%d",
                    row.get("index", "?"),
                    keyword_clean,
                    attempts,
                    self.max_request_attempts,
                )

                try:
                    image_url = self._fetch_preview_png_url(row["detail_url"])
                    if not image_url:
                        row["status"] = "failed"
                        row["last_error"] = "preview_png_not_found"
                        logger.warning(
                            "Preview PNG not found index=%s detail_url=%s",
                            row.get("index", "?"),
                            row.get("detail_url", ""),
                        )
                        if attempts < self.max_request_attempts:
                            self._save_progress(keyword_clean, rows)
                            continue
                        break

                    row["image_url"] = image_url
                    download_ok = self._download_png(image_url, row["file_path"])
                    if not download_ok:
                        row["status"] = "failed"
                        row["last_error"] = "download_failed"
                        logger.warning(
                            "Download failed index=%s image_url=%s",
                            row.get("index", "?"),
                            image_url,
                        )
                        if attempts < self.max_request_attempts:
                            self._save_progress(keyword_clean, rows)
                            continue
                        break

                    row["status"] = "success"
                    row["last_error"] = ""
                    success_count += 1
                    logger.info(
                        "Saved skin index=%s keyword='%s' file=%s",
                        row.get("index", "?"),
                        keyword_clean,
                        row.get("file_path", ""),
                    )
                    break
                except RuntimeError as error:
                    row["status"] = "failed"
                    row["last_error"] = str(error)
                    row["updated_at"] = self._now_iso()
                    self._save_progress(keyword_clean, rows)
                    raise

            if row.get("status") != "success" and attempts >= self.max_request_attempts:
                row["status"] = "failed"

            self._save_progress(keyword_clean, rows)

        failed_count = sum(1 for row in rows if row.get("status") == "failed")
        logger.info(
            "Keyword scrape completed for '%s': success=%d failed=%d target=%d total_rows=%d",
            keyword_clean,
            success_count,
            failed_count,
            target_count,
            len(rows),
        )
        return rows


if __name__ == "__main__":
    scraper = KeywordScraper(output_root="../../../data/skins/bad")
    scraper.scrape_keyword(keyword="test", target_count=5)
