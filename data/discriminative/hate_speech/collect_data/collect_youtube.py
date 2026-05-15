"""YouTube collector: search, enrich metadata and download comments.

The collector is configured via a YAML file (`config.yaml`) which can
define multiple queries, date ranges and limits per job.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import isodate
import yaml
from dateutil.relativedelta import relativedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class YouTubeCollector:
    """YouTube Data API v3-based collector for videos and comments.

    Orchestrates video search, metadata enrichment, and comment download.
    Configured via a YAML file (config.yaml) with support for multiple
    queries, date ranges, and per-job limits.

    Attributes:
        config_path: Path to the configuration file.
        config: Parsed YAML configuration dictionary.
        output_dir: Root output directory for results.
        urls_dir: Subdirectory for video metadata (JSONL).
        comments_dir: Subdirectory for comments (JSONL).
        youtube: Google API client instance.
        logger: Logger instance for the collector.

    Args:
        config_path: Optional path to config.yaml. If not provided, looks for
            config.yaml in the same directory as this module.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path = (
            Path(config_path)
            if config_path
            else Path(__file__).with_name("config.yaml")
        )

        # Load YAML configuration using PyYAML
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with self.config_path.open(encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}

        if not isinstance(cfg, dict):
            raise ValueError("Config file must contain a mapping at top level")

        self.config: Dict[str, Any] = cfg["youtube"]

        self.output_dir = Path(str(self._require("output_dir"))).expanduser()
        self.youtube_api_key = self._require("youtube_api_key")

        self.default_max_videos = int(self._get("defaults.max_videos", 500))
        self.default_max_comments = self._get("defaults.max_comments", None)
        self.default_date_range = self._get("defaults.date_range", None)

        self.job_defaults = {
            "max_videos": int(self._get("jobs.defaults.max_videos", self.default_max_videos)),
            "max_comments": self._get("jobs.defaults.max_comments", self.default_max_comments),
            "date_range": self._get("jobs.defaults.date_range", self.default_date_range),
        }

        self.jobs = self._load_jobs()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.urls_dir = self.output_dir / "urls"
        self.comments_dir = self.output_dir / "comments"
        self.urls_dir.mkdir(parents=True, exist_ok=True)
        self.comments_dir.mkdir(parents=True, exist_ok=True)

        self.logger = self._setup_logger()
        self.youtube = build("youtube", "v3", developerKey=self.youtube_api_key)

        for job in self.jobs:
            self._run_job(job)

    def _get(self, path: str, default: Any = None) -> Any:
        """Get a nested configuration value using dot notation.

        Args:
            path: Dot-separated path (for example "jobs.defaults.max_videos").
            default: Value to return if path is not present.

        Returns:
            The configuration value or ``default`` if missing.
        """
        current: Any = self.config
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return default if current is None else current

    def _require(self, path: str) -> Any:
        """Get a required configuration value; raise if missing.

        Args:
            path: Dot-separated configuration key path.

        Returns:
            The configuration value.

        Raises:
            ValueError: If the path is not found or value is None.
        """
        value = self._get(path)
        if value is None:
            raise ValueError(f"Missing required config value: {path}")
        return value

    def _load_jobs(self) -> List[Dict[str, Any]]:
        """Normalize configured queries from the YAML config.

        Returns:
            A list of job dictionaries with keys: ``query``, ``max_videos``,
            ``max_comments`` and ``date_range``.

        Raises:
            ValueError: When no valid jobs are defined in the configuration.
        """
        jobs = self._get("jobs.queries", None)
        if not jobs:
            query = self._get("query", None)
            if not query:
                raise ValueError("config.yaml must define jobs.queries or a top-level query")
            return [
                {
                    "query": query,
                    "max_videos": self.default_max_videos,
                    "max_comments": self.default_max_comments,
                    "date_range": self.default_date_range,
                }
            ]

        normalized_jobs: List[Dict[str, Any]] = []
        for item in jobs:
            if isinstance(item, str):
                normalized_jobs.append(
                    {
                        "query": item,
                        "max_videos": self.job_defaults["max_videos"],
                        "max_comments": self.job_defaults["max_comments"],
                        "date_range": self.job_defaults["date_range"],
                    }
                )
                continue

            if not isinstance(item, dict):
                continue

            query = item.get("query")
            if not query:
                continue

            normalized_jobs.append(
                {
                    "query": query,
                    "max_videos": item.get("max_videos", self.job_defaults["max_videos"]),
                    "max_comments": item.get("max_comments", self.job_defaults["max_comments"]),
                    "date_range": item.get("date_range", self.job_defaults["date_range"]),
                }
            )

        if not normalized_jobs:
            raise ValueError("config.yaml does not contain valid jobs.queries entries")

        return normalized_jobs

    def _run_job(self, job: Dict[str, Any]) -> None:
        """Execute a single job: search, enrich, filter, and save videos and comments.

        Args:
            job: Job dictionary with keys: query, max_videos, max_comments, date_range.
        """
        query = job["query"]
        max_videos = int(job.get("max_videos", self.default_max_videos) or self.default_max_videos)
        max_comments = job.get("max_comments", self.default_max_comments)
        date_range = job.get("date_range", self.default_date_range)

        self.logger.info("[INICIO] Consulta: %s", query)
        self._all_videos = self._search_videos(query, max_videos, date_range)
        self.logger.info("[BUSQUEDA] %d vídeos encontrados para %s", len(self._all_videos), query)

        self._enrich_with_video_details()
        self._postprocess(query, max_videos, date_range)
        self._save_urls(query)

        for video in self._all_videos:
            self._save_comments(
                video_id=video["video_id"],
                video_url=video["url"],
                filepath=query,
                limit=max_comments,
            )

    def _search_videos(
        self, query: str, max_videos: int, date_range: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Search videos and split the date range into monthly windows when set.

        Args:
            query: Query string to search for.
            max_videos: Maximum number of videos to collect for this job.
            date_range: Optional dictionary with ``from`` and ``to`` dates.

        Returns:
            A list of video metadata dictionaries.
        """
        from_date, to_date = self._parse_date_range(date_range)
        windows = self._build_time_windows(from_date, to_date)

        seen_ids: Set[str] = set()
        videos: List[Dict[str, Any]] = []

        for window_start, window_end in windows:
            if len(videos) >= max_videos:
                break
            chunk = self._search_window(
                query, max_videos - len(videos), window_start, window_end, seen_ids
            )
            videos.extend(chunk)
            self.logger.info(
                "[VENTANA] %s -> %s: %d vídeos | total=%d",
                window_start,
                window_end,
                len(chunk),
                len(videos),
            )

        return videos

    def _search_window(
        self,
        query: str,
        remaining: int,
        published_after: Optional[str],
        published_before: Optional[str],
        seen_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Execute ``search.list`` for a concrete time window.

        The method paginates until it collects ``remaining`` videos or there are
        no more results.

        Args:
            query: Query string to search for.
            remaining: Number of videos still needed.
            published_after: RFC 3339 start datetime (inclusive).
            published_before: RFC 3339 end datetime (exclusive).
            seen_ids: Set of video IDs already found to avoid duplicates.

        Returns:
            List of video metadata dictionaries for this window.
        """
        videos: List[Dict[str, Any]] = []
        next_page_token = None

        while len(videos) < remaining:
            try:
                params = {
                    "q": query,
                    "part": "id,snippet",
                    "type": "video",
                    "maxResults": min(50, remaining - len(videos)),
                    "order": "date",
                }
                if published_after:
                    params["publishedAfter"] = published_after
                if published_before:
                    params["publishedBefore"] = published_before
                if next_page_token:
                    params["pageToken"] = next_page_token

                response = self.youtube.search().list(**params).execute()
            except HttpError as exc:
                self.logger.error("[API ERROR] search.list: %s", exc)
                break

            for item in response.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                if not video_id or video_id in seen_ids:
                    continue

                snippet = item.get("snippet", {})
                video = {
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": snippet.get("title"),
                    "channel": snippet.get("channelTitle"),
                    "published": snippet.get("publishedAt"),
                    "date": snippet.get("publishedAt", "")[:10],
                    "views": None,
                    "duration": None,
                }
                videos.append(video)
                seen_ids.add(video_id)
                self.logger.info("[VIDEO] %s - %s", video.get("title"), video.get("url"))

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        return videos

    def _enrich_with_video_details(self) -> None:
        """Enrich videos with exact publish date, duration and view counts.

        Uses `videos.list` in batches of up to 50 ids.
        """
        ids = [video["video_id"] for video in self._all_videos]

        for index in range(0, len(ids), 50):
            batch = ids[index:index + 50]
            try:
                response = (
                    self.youtube.videos()
                    .list(part="snippet,contentDetails,statistics", id=",".join(batch))
                    .execute()
                )
            except HttpError as exc:
                self.logger.error("[API ERROR] videos.list: %s", exc)
                continue

            details = {item["id"]: item for item in response.get("items", [])}

            for video in self._all_videos[index:index + 50]:
                detail = details.get(video["video_id"])
                if not detail:
                    continue
                snippet = detail.get("snippet", {})
                stats = detail.get("statistics", {})
                content = detail.get("contentDetails", {})

                published_at = snippet.get("publishedAt", "")
                if published_at:
                    video["date"] = published_at[:10]
                    video["published"] = published_at

                raw_duration = content.get("duration", "")
                if raw_duration:
                    try:
                        td = isodate.parse_duration(raw_duration)
                        total_seconds = int(td.total_seconds())
                        hours, remainder = divmod(total_seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        if hours:
                            video["duration"] = f"{hours}:{minutes:02d}:{seconds:02d}"
                        else:
                            video["duration"] = f"{minutes}:{seconds:02d}"
                    except (isodate.ISO8601Error, TypeError, AttributeError) as exc:
                        self.logger.warning("[DURATION] Could not parse duration %s: %s", raw_duration, exc)
                        video["duration"] = raw_duration

                video["views"] = stats.get("viewCount")

    def _postprocess(self, query: str, max_videos: int, date_range: Optional[Dict[str, Any]]) -> None:
        """Filter videos by normalized query and date range.

        Args:
            query: Original query string.
            max_videos: Maximum videos to keep after filtering.
            date_range: Optional date_range dict as supplied in the config.
        """
        norm_query = self._normalize(query)
        before_count = len(self._all_videos)

        from_date, to_date = self._parse_date_range(date_range)
        from_dt = datetime.fromisoformat(from_date.replace("Z", "")).date() if from_date else None
        to_dt = datetime.fromisoformat(to_date.replace("Z", "")).date() if to_date else None

        filtered: List[Dict[str, Any]] = []
        for video in self._all_videos:
            if norm_query not in self._normalize(video.get("title", "")):
                continue

            raw_date = video.get("date", "")
            if raw_date:
                try:
                    video_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                    if from_dt and video_date < from_dt:
                        continue
                    if to_dt and video_date > to_dt:
                        continue
                except ValueError:
                    pass

            filtered.append(video)

        removed = before_count - len(filtered)
        self._all_videos = filtered[:max_videos]
        self.logger.info(
            "[FILTRADO] %d vídeos eliminados, %d conservados. Guardando los %d primeros.",
            removed,
            len(filtered),
            len(self._all_videos),
        )

    def _save_comments(
        self,
        video_id: str,
        video_url: str,
        filepath: str,
        limit: Optional[int] = None,
    ) -> None:
        """Download paginated comments and merge with existing ones without duplicates.

        Args:
            video_id: YouTube video id.
            video_url: Full URL to the video.
            filepath: Job identifier used to name the output file.
            limit: Optional maximum number of comments to collect for this video.
        """
        new_comments: List[Dict[str, Any]] = []
        next_page_token = None

        while True:
            if limit is not None and len(new_comments) >= limit:
                break

            try:
                params = {
                    "part": "snippet",
                    "videoId": video_id,
                    "maxResults": 100,
                    "order": "time",
                    "textFormat": "plainText",
                }
                if next_page_token:
                    params["pageToken"] = next_page_token

                response = self.youtube.commentThreads().list(**params).execute()
            except HttpError as exc:
                self.logger.warning(
                    "[COMENTARIOS] No se pueden obtener comentarios de %s: %s",
                    video_url,
                    exc,
                )
                break

            for item in response.get("items", []):
                top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                new_comments.append(
                    {
                        "cid": item.get("id"),
                        "video_url": video_url,
                        "text": top.get("textDisplay"),
                        "author": top.get("authorDisplayName"),
                        "likes": top.get("likeCount", 0),
                        "published_at": top.get("publishedAt"),
                        "updated_at": top.get("updatedAt"),
                        "reply_count": item.get("snippet", {}).get("totalReplyCount", 0),
                    }
                )

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        if limit is not None:
            new_comments = new_comments[:limit]

        output_path = self.comments_dir / f"{self._job_stem(filepath)}.jsonl"
        self._merge_jsonl(
            output_path, new_comments, lambda item: (item.get("cid"), item.get("video_url"))
        )
        self.logger.info("[COMENTARIOS] %d comentarios nuevos de %s", len(new_comments), video_url)

    def _save_urls(self, filepath: str) -> None:
        """Save the final list of videos to a JSONL file.

        Args:
            filepath: Job identifier used to name the output file.
        """
        output_path = self.urls_dir / f"{self._job_stem(filepath)}.jsonl"
        self._merge_jsonl(output_path, self._all_videos, lambda item: item.get("video_id"))
        self.logger.info("[URLS] %d vídeos guardados en %s", len(self._all_videos), output_path)

    def _parse_date_range(self, date_range: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        """Convert a ``date_range`` spec into RFC 3339 datetimes for the API.

        Args:
            date_range: Mapping with optional keys ``from`` and ``to`` where
                dates are in ``DD/MM/YYYY`` format or the string ``"today"``.

        Returns:
            A tuple with (published_after, published_before) RFC3339 strings
            or ``(None, None)`` when not provided.
        
        Raises:
            ValueError: When date strings cannot be parsed using ``DD/MM/YYYY``.
        """
        if not date_range:
            return None, None

        published_after = None
        published_before = None

        if date_range.get("from"):
            start_date = datetime.strptime(date_range["from"], "%d/%m/%Y")
            published_after = start_date.strftime("%Y-%m-%dT00:00:00Z")

        if date_range.get("to"):
            raw_to = date_range["to"]
            if isinstance(raw_to, str) and raw_to.lower() == "today":
                end_date = datetime.utcnow()
            else:
                end_date = datetime.strptime(raw_to, "%d/%m/%Y")
            published_before = (end_date + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

        return published_after, published_before

    def _build_time_windows(
        self, published_after: Optional[str], published_before: Optional[str]
    ) -> List[Tuple[Optional[str], Optional[str]]]:
        """Split the time range into monthly windows.

        When either boundary is missing, returns a single window with the
        provided values.
        """
        if not published_after or not published_before:
            return [(published_after, published_before)]

        start = datetime.fromisoformat(published_after.replace("Z", ""))
        end = datetime.fromisoformat(published_before.replace("Z", ""))

        windows: List[Tuple[str, str]] = []
        cursor = start
        while cursor < end:
            next_cursor = cursor + relativedelta(months=1)
            window_end = min(next_cursor, end)
            windows.append(
                (
                    cursor.strftime("%Y-%m-%dT00:00:00Z"),
                    window_end.strftime("%Y-%m-%dT00:00:00Z"),
                )
            )
            cursor = next_cursor

        windows.reverse()
        return windows

    @staticmethod
    def _normalize(text: Optional[str]) -> str:
        """Return a simplified, lowercased version of `text` suitable for matching."""
        if not text:
            return ""
        normalized = text.lower()
        normalized = re.sub(r"[^a-z0-9áéíóúüñ]", "", normalized)
        return normalized

    @staticmethod
    def _job_stem(value: str) -> str:
        """Convert a query string into a filesystem-safe stem.

        Returns a lowercase string with spaces replaced by underscores and
        non-allowed characters removed.
        """
        stem = value.strip().lower()
        stem = re.sub(r"\s+", "_", stem)
        stem = re.sub(r"[^a-z0-9áéíóúüñ_]+", "", stem)
        return stem or "query"

    @staticmethod
    def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
        """Read a JSONL file and return a list of records.

        Returns an empty list when the file does not exist.
        """
        records: List[Dict[str, Any]] = []
        if not path.exists():
            return records

        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    @staticmethod
    def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
        """Write a list of dictionaries to a JSONL file."""
        with path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _merge_jsonl(
        self, path: Path, new_records: List[Dict[str, Any]], key_fn: Callable[[Dict[str, Any]], Any]
    ) -> None:
        """Merge new records with existing JSONL file, avoiding duplicates.

        Args:
            path: Path to the JSONL file.
            new_records: New records to merge.
            key_fn: Callable that returns a unique key for a record.
        """
        existing = self._read_jsonl(path)
        seen = {key_fn(record) for record in existing}

        merged = list(existing)
        for record in new_records:
            key = key_fn(record)
            if key in seen:
                continue
            merged.append(record)
            seen.add(key)

        self._write_jsonl(path, merged)

    def _setup_logger(self) -> logging.Logger:
        """Configure and return a logger used by the collector."""
        logger = logging.getLogger(f"youtube_{self.output_dir.name}")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            log_path = self.output_dir / "youtube.log"
            file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
            file_handler.setLevel(logging.INFO)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        return logger


def main() -> None:
    """Entry point: parse arguments and instantiate the collector."""
    parser = argparse.ArgumentParser(description="Run the YouTube collector from config.yaml")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    args = parser.parse_args()

    YouTubeCollector(config_path=args.config)


if __name__ == "__main__":
    main()
