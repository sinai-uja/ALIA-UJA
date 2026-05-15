"""TikTok Research API helper for dataset collection.

This module exposes the ``TikTokAPI`` class to fetch videos and comments,
persist raw JSON files, and keep execution logs.

Typical usage example:
    tk = TikTokAPI(config_path='config.yaml', dataset_path='./data')
    tk.get_comments_by_hashtaglist(['hashtag1', 'hashtag2'])
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

import yaml
from tiktok_research_api import (
    Criteria,
    Query,
    QueryVideoCommentsRequest,
    QueryVideoRequest,
    TikTokResearchAPI,
)


class TikTokAPI:
    """Client wrapper to collect TikTok videos and comments.

    Attributes:
        dataset_folder: Base output directory for the current run.
        api: TikTokResearchAPI client instance.
        videos_jsonl_path: Path to file storing video data.
        comments_jsonl_path: Path to file storing comments data.
        region_criteria: Region filter criteria for queries.
    """

    def __init__(
        self,
        config_path: str,
        dataset_path: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Initializes API client and output structure.

        Args:
            config_path: Path to YAML configuration file.
            dataset_path: Destination directory for collected data.
            params: Optional runtime overrides, e.g. {'qps': 10}.

        Raises:
            KeyError: If required configuration keys are missing.
            FileNotFoundError: If config file is not found.
        """
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

        self.params = params or {}
        self._tiktok_cfg = self.config["tiktok_cfg"]
        self._query_cfg = self._tiktok_cfg["query"]
        self._logging_cfg = self.config["logging"]
        self._output_cfg = self.config["output"]

        self._default_video_fields = self._query_cfg["default_video_fields"]
        self._default_start_date = self._query_cfg["default_start_date"]
        self._default_end_date = self._query_cfg["default_end_date"]
        self._default_max_count = self._query_cfg["max_count"]
        self._default_max_total = self._query_cfg["max_total"]

        qps = self.params.get("qps", self._tiktok_cfg["qps"])
        self.api = TikTokResearchAPI(
            client_key=self._tiktok_cfg["client_key"],
            client_secret=self._tiktok_cfg["client_secret"],
            qps=qps,
        )

        # Output directories and JSONL files
        self.dataset_folder = dataset_path
        os.makedirs(self.dataset_folder, exist_ok=True)

        self.videos_jsonl_path = os.path.expanduser(
            os.path.join(
                self.dataset_folder, self._output_cfg["videos_file"]
            )
        )
        self.comments_jsonl_path = os.path.expanduser(
            os.path.join(
                self.dataset_folder, self._output_cfg["comments_file"]
            )
        )

        # Track processed IDs to avoid duplicates in single run
        self._processed_video_ids = set()
        self._processed_comment_ids = set()

        self.region_criteria = Criteria(
            operation="EQ",
            field_name="region_code",
            field_values=[self._query_cfg["region_code"]],
        )

        self.logger = self.setup_logger()
        self.logger.info("[INIT] TikTok Research API initialized")

    def _video_request(
        self,
        query: Query,
        video_fields: Sequence[str],
        start_date: str,
        end_date: str,
        max_count: int,
        max_total: int,
        search_id: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> tuple[Any, ...]:
        """Builds and executes a video query request.

        Args:
            query: Query object with filtering criteria.
            video_fields: List of fields to retrieve for videos.
            start_date: Start date in YYYYMMDD format.
            end_date: End date in YYYYMMDD format.
            max_count: Max results per page.
            max_total: Max total results to retrieve.
            search_id: Optional search ID for pagination.
            cursor: Optional cursor for pagination.

        Returns:
            Tuple containing videos, search_id, cursor, has_more, and date info.
        """
        video_request = QueryVideoRequest(
            fields=video_fields,
            query=query,
            start_date=start_date,
            end_date=end_date,
            max_count=max_count,
            max_total=max_total,
            search_id=search_id,
            cursor=cursor,
        )

        return self.api.query_videos(
            video_request, fetch_all_pages=True
        )

    def check_json(self, folder: str, json_id: str) -> bool:
        """Checks whether a record with given ID already exists in JSONL (this run).

        Args:
            folder: Unused (kept for compatibility).
            json_id: Record ID to check.

        Returns:
            True if already processed in this run, False otherwise.
        """
        # Check in-memory cache to avoid re-processing in same run
        if "video" in json_id or folder == self.videos_jsonl_path:
            return json_id in self._processed_video_ids
        else:
            return json_id in self._processed_comment_ids

    def append_jsonl(
        self,
        jsonl_path: str,
        records: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
        record_type: str,
    ) -> None:
        """Appends records to a JSONL file (one JSON object per line).

        Args:
            jsonl_path: Path to the JSONL file.
            records: Single dict or list of dicts to append.
            record_type: 'video' or 'comment' to track IDs.

        Raises:
            ValueError: If record_type is not 'video' or 'comment'.
            IOError: If unable to write to file.
        """
        if record_type not in ("video", "comment"):
            raise ValueError(
                f"record_type must be 'video' or 'comment', "
                f"got {record_type}"
            )

        if not isinstance(records, list):
            records = [records]

        with open(jsonl_path, "a", encoding="utf-8") as f:
            for record in records:
                json.dump(record, f, ensure_ascii=False)
                f.write("\n")

                # Track processed IDs
                if record_type == "video":
                    self._processed_video_ids.add(record.get("id"))
                elif record_type == "comment":
                    self._processed_comment_ids.add(record.get("id"))

    def get_comments_by_id(
        self, video_id: str, max_count: Optional[int] = None
    ) -> None:
        """Fetches comments for a single video and appends to JSONL.

        Args:
            video_id: ID of the video to fetch comments for.
            max_count: Maximum number of comments to fetch.

        Raises:
            IOError: If unable to write comments to file.
        """
        if max_count is None:
            max_count = self._default_max_count

        # Check if already processed in this run
        if self.check_json(self.comments_jsonl_path, video_id):
            self.logger.info(
                "[COMMENTS] video id %s already processed in this "
                "run. Skipping...",
                video_id,
            )
            return

        video_comment_request = QueryVideoCommentsRequest(
            video_id=video_id,
            max_count=max_count,
        )
        comments, cursor, has_more = (
            self.api.query_video_comments(
                video_comment_request, fetch_all_pages=True
            )
        )
        if comments:
            self.append_jsonl(
                self.comments_jsonl_path, comments, "comment"
            )
            self.logger.info(
                "[COMMENTS] id %s - Appended %d comments to %s",
                video_id,
                len(comments),
                self._output_cfg["comments_file"],
            )
        else:
            self.logger.info(
                "[COMMENTS] id %s - No comments available", video_id
            )

    def get_comments_by_hashtaglist(
        self,
        hashtaglist: Sequence[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        video_fields: Optional[Sequence[str]] = None,
        max_count: Optional[int] = None,
        max_total: Optional[int] = None,
    ) -> None:
        """Fetches comments for all videos from a hashtag list.

        Args:
            hashtaglist: List of hashtags to process.
            start_date: Start date in YYYYMMDD format or 'today'.
            end_date: End date in YYYYMMDD format or 'today'.
            video_fields: List of fields to retrieve for videos.
            max_count: Maximum results per page.
            max_total: Maximum total results to retrieve.

        Raises:
            IOError: If unable to read or write data files.
        """
        start_date = start_date or self._default_start_date
        end_date = end_date or self._default_end_date
        video_fields = video_fields or self._default_video_fields
        max_count = (
            max_count
            if max_count is not None
            else self._default_max_count
        )
        max_total = (
            max_total
            if max_total is not None
            else self._default_max_total
        )

        # Track videos already processed for comments in this call
        processed_video_ids = set()

        for hashtag in hashtaglist:
            # First fetch videos for this hashtag
            self.get_videos_by_hashtag(
                hashtag,
                start_date,
                end_date,
                video_fields,
                max_count,
                max_total,
            )

            # Now read videos from JSONL and fetch comments
            if not os.path.exists(self.videos_jsonl_path):
                self.logger.warning(
                    "[HASHTAG] No videos file found for #%s", hashtag
                )
                continue

            self.logger.info(
                "[HASHTAG] Processing comments for #%s", hashtag
            )
            with open(
                self.videos_jsonl_path, "r", encoding="utf-8"
            ) as f:
                for line in f:
                    video = json.loads(line)
                    video_id = video.get("id")
                    if (
                        video_id not in processed_video_ids
                        and video.get("comment_count", 0) > 0
                    ):
                        self.get_comments_by_id(video_id, max_count)
                        processed_video_ids.add(video_id)

    def get_videos_by_hashtag(
        self,
        hashtag: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        video_fields: Optional[Sequence[str]] = None,
        max_count: Optional[int] = None,
        max_total: Optional[int] = None,
    ) -> None:
        """Fetches videos for one hashtag and appends to JSONL.

        Args:
            hashtag: Hashtag to search for.
            start_date: Start date in YYYYMMDD format or 'today'.
            end_date: End date in YYYYMMDD format or 'today'.
            video_fields: List of fields to retrieve for videos.
            max_count: Maximum results per page.
            max_total: Maximum total results to retrieve.

        Raises:
            IOError: If unable to write videos to file.
        """
        start_date = start_date or self._default_start_date
        end_date = end_date or self._default_end_date
        video_fields = video_fields or self._default_video_fields
        max_count = (
            max_count
            if max_count is not None
            else self._default_max_count
        )
        max_total = (
            max_total
            if max_total is not None
            else self._default_max_total
        )

        if end_date == "today":
            end_date = datetime.now().strftime("%Y%m%d")

        if self.check_json(
            self.videos_jsonl_path, f"hashtag_{hashtag}"
        ):
            self.logger.info(
                "[HASHTAG] #%s already processed in this run. "
                "Skipping...",
                hashtag,
            )
            return

        self.logger.info("[HASHTAG] Fetching videos for #%s", hashtag)
        hashtag_criteria = Criteria(
            operation="EQ",
            field_name="hashtag_name",
            field_values=[hashtag],
        )

        query = Query(
            and_criteria=[hashtag_criteria, self.region_criteria]
        )

        video_request = QueryVideoRequest(
            fields=video_fields,
            query=query,
            start_date=start_date,
            end_date=end_date,
            max_count=max_count,
            max_total=max_total,
        )

        (
            videos,
            search_id,
            cursor,
            has_more,
            start_date,
            end_date,
        ) = self.api.query_videos(
            video_request, fetch_all_pages=True
        )
        if videos:
            self.append_jsonl(
                self.videos_jsonl_path, videos, "video"
            )
            self.logger.info(
                "[HASHTAG] #%s - Appended %d videos to %s",
                hashtag,
                len(videos),
                self._output_cfg["videos_file"],
            )
        else:
            self.logger.info(
                "[HASHTAG] #%s - No videos found", hashtag
            )

    def get_videos_by_hashtaglist(
        self,
        hashtaglist: Sequence[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        video_fields: Optional[Sequence[str]] = None,
        max_count: Optional[int] = None,
        max_total: Optional[int] = None,
    ) -> None:
        """Fetches videos for all hashtags in hashtaglist.

        Args:
            hashtaglist: List of hashtags to process.
            start_date: Start date in YYYYMMDD format or 'today'.
            end_date: End date in YYYYMMDD format or 'today'.
            video_fields: List of fields to retrieve for videos.
            max_count: Maximum results per page.
            max_total: Maximum total results to retrieve.

        Raises:
            IOError: If unable to write videos to file.
        """
        start_date = start_date or self._default_start_date
        end_date = end_date or self._default_end_date
        video_fields = video_fields or self._default_video_fields
        max_count = (
            max_count
            if max_count is not None
            else self._default_max_count
        )
        max_total = (
            max_total
            if max_total is not None
            else self._default_max_total
        )

        for hashtag in hashtaglist:
            self.get_videos_by_hashtag(
                hashtag,
                start_date,
                end_date,
                video_fields,
                max_count,
                max_total,
            )

    def setup_logger(self) -> logging.Logger:
        """Creates a logger writing both to file and stdout.

        Logs are written to the directory specified in
        config.logging.logs_dir.

        Returns:
            Configured logger instance.

        Raises:
            IOError: If unable to create log directory or file.
        """
        logger = logging.getLogger(
            os.path.basename(self.dataset_folder)
        )
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logs_dir = os.path.expanduser(
                self._logging_cfg["logs_dir"]
            )
            os.makedirs(logs_dir, exist_ok=True)
            log_path = os.path.join(
                logs_dir, self._logging_cfg["log_filename"]
            )

            fh = logging.FileHandler(log_path, "a", "utf-8")
            ch = logging.StreamHandler()
            fmt = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
            fh.setFormatter(fmt)
            ch.setFormatter(fmt)
            logger.addHandler(fh)
            logger.addHandler(ch)
        logger.propagate = False
        return logger


def load_config(
    path: str = "config.yaml",
) -> Mapping[str, Any]:
    """Loads configuration from a YAML file.

    Args:
        path: Path to the configuration YAML file.

    Returns:
        Dictionary containing configuration data.

    Raises:
        FileNotFoundError: If config file is not found.
        yaml.YAMLError: If config file is not valid YAML.
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    """Main entrypoint for TikTok data collection.

    Reads config.yaml and runs the collection job defined under
    jobs.hashtags. Idempotent: previously-downloaded JSON files are
    skipped, so interrupted runs can be resumed safely.

    Raises:
        SystemExit: On collection error with exit code 1.
    """
    config = load_config("config.yaml")["tiktok"]
    paths_cfg = config["paths"]
    hashtags_job = config["jobs"]["hashtags"]
    dataset_path = os.path.expanduser(
        os.path.join(
            paths_cfg["base_output_dir"],
            hashtags_job["output_subdir"],
        )
    )

    tk = TikTokAPI(
        config_path="config.yaml", dataset_path=dataset_path
    )

    try:
        tk.get_comments_by_hashtaglist(
            hashtaglist=hashtags_job["hashtags"],
            start_date=hashtags_job["start_date"],
            end_date=hashtags_job["end_date"],
            max_count=hashtags_job["max_count"],
            max_total=hashtags_job["max_total"],
        )
    except (IOError, OSError, KeyError) as e:
        tk.logger.exception(
            "Collection interrupted due to %s error. "
            "Resume by re-running this script.",
            type(e).__name__,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
