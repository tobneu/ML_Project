import logging
import random
import re
import time
from pathlib import Path
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://www.minecraftskins.com"
SEARCH_PATH = "/search/mostvotedskin/{keyword}/{page}/"
DOWNLOAD_PATH = "/skin/download/{skin_id}"
SKIN_LINK_PATTERN = re.compile(r"/skin/(\d+)/")

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class SkindexScraper:
    """Scrapes skin IDs by keyword and downloads PNGs through direct download endpoints."""

    def __init__(
        self,
        retry_attempts: int = 3,
        retry_sleep_seconds: float = 2.0,
        politeness_sleep_range: tuple[float, float] = (1.0, 3.0),
        timeout_seconds: int = 25,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be >= 1")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")

        self.retry_attempts = retry_attempts
        self.retry_sleep_seconds = retry_sleep_seconds
        self.politeness_sleep_range = politeness_sleep_range
        self.timeout_seconds = timeout_seconds
        self.session = cloudscraper.create_scraper()

    def _build_search_url(self, keyword: str, page: int) -> str:
        return f"{BASE_URL}{SEARCH_PATH.format(keyword=keyword, page=page)}"

    def _build_download_url(self, skin_id: str) -> str:
        return f"{BASE_URL}{DOWNLOAD_PATH.format(skin_id=skin_id)}"

    def _request_with_retries(self, url: str, expect_binary: bool = False) -> Optional[bytes | str]:
        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
            except Exception as error:  # pragma: no cover - network errors are non-deterministic
                if attempt == self.retry_attempts:
                    logger.warning("Request failed after %d attempts for %s: %s", self.retry_attempts, url, error)
                    return None
                logger.warning("Request attempt %d/%d failed for %s: %s", attempt, self.retry_attempts, url, error)
                time.sleep(self.retry_sleep_seconds)
                continue

            if response.status_code in (403, 429):
                if attempt == self.retry_attempts:
                    logger.warning("Received %d after %d attempts for %s", response.status_code, self.retry_attempts, url)
                    return None
                logger.warning(
                    "Received %d for %s (attempt %d/%d), waiting %.1fs",
                    response.status_code,
                    url,
                    attempt,
                    self.retry_attempts,
                    self.retry_sleep_seconds,
                )
                time.sleep(self.retry_sleep_seconds)
                continue

            if 400 <= response.status_code < 500:
                logger.warning("Client error %d for %s", response.status_code, url)
                return None

            try:
                response.raise_for_status()
            except Exception as error:  # pragma: no cover - network errors are non-deterministic
                if attempt == self.retry_attempts:
                    logger.warning("Server error after %d attempts for %s: %s", self.retry_attempts, url, error)
                    return None
                logger.warning("Server error %s (attempt %d/%d), waiting %.1fs", url, attempt, self.retry_attempts, self.retry_sleep_seconds)
                time.sleep(self.retry_sleep_seconds)
                continue

            return response.content if expect_binary else response.text

        return None

    def parse_skin_ids(self, search_html: str) -> list[str]:
        """Extract unique skin IDs from a keyword search page."""
        soup = BeautifulSoup(search_html, "html.parser")
        skin_ids: list[str] = []
        seen: set[str] = set()

        for link in soup.find_all("a", href=True):
            href = link["href"]
            match = SKIN_LINK_PATTERN.search(href)
            if not match:
                continue

            skin_id = match.group(1)
            if skin_id in seen:
                continue
            seen.add(skin_id)
            skin_ids.append(skin_id)

        return skin_ids

    def fetch_skin_ids_for_page(self, keyword: str, page: int) -> list[str]:
        search_url = self._build_search_url(keyword=keyword, page=page)
        html = self._request_with_retries(search_url, expect_binary=False)
        if html is None:
            return []
        return self.parse_skin_ids(html)

    def download_skin_by_id(self, skin_id: str, destination_path: Path, overwrite: bool = False) -> bool:
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if destination_path.exists() and not overwrite:
            logger.info("Skip existing skin file: %s", destination_path)
            return True

        download_url = self._build_download_url(skin_id=skin_id)
        content = self._request_with_retries(download_url, expect_binary=True)
        if content is None:
            return False

        destination_path.write_bytes(content)

        low, high = self.politeness_sleep_range
        sleep_time = random.uniform(low, high)
        time.sleep(sleep_time)
        return True

    def scrape_keyword(
        self,
        keyword: str,
        target_count: int,
        output_root: Path,
        start_page: int = 1,
        max_pages: int = 1000,
        overwrite: bool = False,
    ) -> list[Path]:
        """Scrape skins for one keyword until target_count files are available locally."""
        if target_count < 1:
            raise ValueError("target_count must be >= 1")
        if start_page < 1:
            raise ValueError("start_page must be >= 1")

        keyword = keyword.strip().lower()
        if not keyword:
            raise ValueError("keyword must not be empty")

        keyword_dir = output_root / keyword
        keyword_dir.mkdir(parents=True, exist_ok=True)

        downloaded_paths: list[Path] = []
        seen_ids: set[str] = set()

        logger.info("Keyword scrape start: keyword=%s target_count=%d", keyword, target_count)

        for page in range(start_page, start_page + max_pages):
            if len(downloaded_paths) >= target_count:
                break

            skin_ids = self.fetch_skin_ids_for_page(keyword=keyword, page=page)
            if not skin_ids:
                logger.info("No skin IDs found on page %d, stopping.", page)
                break

            logger.info("Page %d yielded %d skin IDs", page, len(skin_ids))

            for skin_id in skin_ids:
                if len(downloaded_paths) >= target_count:
                    break
                if skin_id in seen_ids:
                    continue
                seen_ids.add(skin_id)

                file_path = keyword_dir / f"{keyword}_{skin_id}.png"
                success = self.download_skin_by_id(skin_id=skin_id, destination_path=file_path, overwrite=overwrite)
                if not success:
                    logger.warning("Failed to download skin_id=%s", skin_id)
                    continue

                downloaded_paths.append(file_path)
                logger.info("Progress: %d/%d | %s", len(downloaded_paths), target_count, file_path.name)

        logger.info("Keyword scrape done: downloaded=%d target=%d keyword=%s", len(downloaded_paths), target_count, keyword)
        return downloaded_paths


def run(
    keyword: str,
    target_count: int,
    output_root: str = "../../../data/skins/bad",
    retry_attempts: int = 3,
    retry_sleep_seconds: float = 2.0,
    politeness_sleep_range: tuple[float, float] = (1.0, 3.0),
    timeout_seconds: int = 25,
    start_page: int = 1,
    max_pages: int = 1000,
    overwrite: bool = False,
) -> list[Path]:
    scraper = SkindexScraper(
        retry_attempts=retry_attempts,
        retry_sleep_seconds=retry_sleep_seconds,
        politeness_sleep_range=politeness_sleep_range,
        timeout_seconds=timeout_seconds,
    )
    return scraper.scrape_keyword(
        keyword=keyword,
        target_count=target_count,
        output_root=Path(output_root),
        start_page=start_page,
        max_pages=max_pages,
        overwrite=overwrite,
    )


if __name__ == "__main__":
    run(keyword="uniform", target_count=25)

