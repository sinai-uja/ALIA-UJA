# Hate Speech Data Collection (TikTok + YouTube)

This directory centralizes raw data collection for the hate speech task across two platforms:

- TikTok (Research API)
- YouTube (Data API v3)

## Current structure of `collect_data`

```text
collect_data/
  collect_tiktok.py
  collect_youtube.py
  config.yaml
  environment.yml
```

## Main files

### `collect_tiktok.py`
Collection script using the TikTok Research API.

**`TikTokAPI` class** (API wrapper):
- `__init__(config_path, dataset_path)`: Initializes client with credentials from config.yaml.
- `get_comments_by_hashtaglist(hashtaglist, ...)`: Orchestrates video and comment collection for a list of hashtags.
- `get_videos_by_hashtag(hashtag, ...)`: Fetches videos for a specific hashtag.
- `get_comments_by_id(video_id, ...)`: Fetches comments for a video.
- `append_jsonl(jsonl_path, records, record_type)`: Append-only write to JSONL with in-memory deduplication.
- `setup_logger()`: Configures logging to file and stdout.

**Execution flow (`main()`):**
1. Reads the `tiktok` section from config.yaml.
2. Builds output path: `{base_output_dir}/{output_subdir}/`.
3. Instantiates `TikTokAPI` with config and dataset path.
4. Runs `get_comments_by_hashtaglist()` for all hashtags in config.
5. Catches IOError/OSError/KeyError exceptions and logs them with full traceback.

**Features:**
- Idempotency: Within a single run, avoids duplicates by ID in memory.
- Across runs: JSONL files are append-only; already-saved records are not re-collected.
- Fixed region: Always filters by `region_code: ES` (Spain).
- Configurable video fields via `tiktok.query.default_video_fields`.

**Run:**
```bash
python collect_tiktok.py
```

**Expected output:**
- `{output_subdir}/videos_raw.jsonl` (videos, one per line)
- `{output_subdir}/comments_raw.jsonl` (comments, one per line)
- Log at the configured location

---

### `collect_youtube.py`
Collection script using the YouTube Data API v3.

**`YouTubeCollector` class** (orchestrator):
- `__init__(config_path=None)`: Loads config, instantiates YouTube API client, runs jobs.
- `_run_job(job)`: Runs a full job: search → enrichment → filtering → saving.
- `_search_videos(query, max_videos, date_range)`: Search using monthly time windows.
- `_search_window(...)`: Runs `search.list` with pagination for a single time window.
- `_enrich_with_video_details()`: Enriches metadata via `videos.list` (duration, views, exact date).
- `_postprocess(query, max_videos, date_range)`: Filters by normalized query and date range.
- `_save_comments(video_id, ...)`: Downloads comments via `commentThreads.list` and merges into JSONL.
- `_save_urls(filepath)`: Saves the final list of videos.
- `_merge_jsonl(path, new_records, key_fn)`: Merge with deduplication.

**Search strategy:**
- Supports multiple queries via `jobs.queries`.
- Splits date range into monthly windows to broaden coverage.
- Normalizes titles (lowercase, special characters) before final filtering.
- Deduplicates by `video_id` across windows.

**Execution flow:**
1. Loads config from `config.yaml` (defaults to same directory).
2. For each job in `jobs.queries`:
   - Searches videos (with pagination over monthly windows).
   - Enriches with `videos.list` (duration, views, exact date).
   - Filters by normalized query and date range.
   - Downloads comments for each video (up to `max_comments` per video).
3. Saves results to JSONL with deduplication.

**Run:**
```bash
python collect_youtube.py
```

With an alternate config:
```bash
python collect_youtube.py --config /path/to/config.yaml
```

**Expected output:**
- `urls/{query_stem}.jsonl` (video metadata: id, url, title, channel, date, views, duration)
- `comments/{query_stem}.jsonl` (comments: cid, video_url, text, author, likes, published_at, reply_count)
- `youtube.log` (logs in `output_dir`)

**Example JSONL structure:**
```json
{"video_id": "abc123", "url": "https://youtube.com/watch?v=abc123", "title": "...", "views": "1000", "duration": "5:30", "date": "2025-09-10"}
{"cid": "xyz789", "video_url": "https://youtube.com/watch?v=abc123", "text": "Great video!", "author": "User123", "likes": 5, "published_at": "2025-09-10T12:30:00Z"}
```

---

### `config.yaml.example`
Unified configuration file in YAML format for both platforms.

---

### `environment.yml`
Conda environment specification file.

**Typical contents:**
```yaml
name: collect_data
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.10
  - pyyaml
  - pip
  - pip:
    - tiktok-research-api
    - google-api-python-client
    - python-dateutil
    - isodate
```

**Usage:**
```bash
conda env create -f environment.yml
conda activate collect_data
python collect_tiktok.py
python collect_youtube.py
```

---

## Dependency configuration

### Installation with conda
The `environment.yml` file bundles all required dependencies:

```bash
conda env create -f environment.yml  # Creates 'collect_data' environment
conda activate collect_data
```

### Explicit dependencies

| Package | Use | Minimum version |
|---------|-----|-----------------|
| `pyyaml` | Reading config.yaml | — |
| `tiktok_research_api` | TikTok Research API client | — |
| `google-api-python-client` | YouTube Data API v3 client | — |
| `python-dateutil` | Date parsing (YouTube) | — |
| `isodate` | ISO 8601 duration parsing (YouTube) | — |

### Credentials setup

**TikTok Research API:**
- Requires formal access to the [TikTok Research API](https://developers.tiktok.com/products/research-api/)
- Obtain `client_key` and `client_secret`
- Specify in `config.yaml` → `tiktok.tiktok_cfg`

**YouTube Data API v3:**
- Create a project in the [Google Cloud Console](https://console.cloud.google.com/)
- Enable YouTube Data API v3
- Create an "API Key" credential
- Specify in `config.yaml` → `youtube.youtube_api_key`

## API quota limits

### TikTok Research API
- **Daily limit**: 1,000 requests
- **Max records/day**: 100,000 total records (videos + comments combined)
- **Reset**: 12:00 AM UTC daily
- **Rate limiting**: Configurable via `tiktok.tiktok_cfg.qps` (queries per second)

**Implication:** If interrupted due to quota, wait until 12:00 AM UTC and re-run (idempotent).

### YouTube Data API v3
- **Free tier**: 10,000 units/day
- **Operation costs**:
  - `search.list`: 100 units/call
  - `videos.list`: 1 unit/call
  - `commentThreads.list`: 1 unit/call

**Implication:** Limit `max_videos` per query to avoid exhausting the daily unit budget.

## Typical workflow

### Setup
1. Edit `config.yaml`:
   - TikTok: Add credentials, paths, hashtag list, dates, limits.
   - YouTube: Add API key, queries, date_range, limits.
2. Run `conda env create -f environment.yml && conda activate collect_data`.

### Execution
3. Run the collectors:
   ```bash
   python collect_tiktok.py    # Collects by hashtags
   python collect_youtube.py   # Collects by search queries
   ```
4. Monitor logs (`tiktok.log`, `youtube.log`) for progress and errors.

### Resuming after interruption
- Both scripts are idempotent (JSONL append-only, deduplication by ID).
- If interrupted due to quota or network issues, simply re-run the script.
- Already-collected data will not be duplicated.

### Validating results
```bash
# TikTok
wc -l {output_subdir}/videos_raw.jsonl    # Number of videos
wc -l {output_subdir}/comments_raw.jsonl  # Number of comments

# YouTube
ls -lh urls/                               # Video JSONL files
ls -lh comments/                           # Comment JSONL files
```

## Operational notes

- The `collect_data` directory is the central operational entry point.
- Both platforms use official APIs with quota restrictions. Adjust limits in `config.yaml` as needed.
- Data is stored in JSONL format (append-only) for maximum compatibility and downstream processing efficiency.
- Each JSONL line is a complete, self-contained valid JSON object (do not assume any particular ordering or differentiated structure).