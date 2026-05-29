# Comments Curation Pipeline

This directory contains the code and configuration used to curate hate-speech comments collected from YouTube and TikTok. The workflow filters raw JSONL comments, anonymizes user mentions, removes duplicates with MinHash, and writes a final combined dataset for downstream use.

The implementation is based on [datatrove](https://github.com/huggingface/datatrove), the same pipeline family used by Hugging Face to prepare large-scale corpora such as [HuggingFaceFW/fineweb](https://huggingface.co/datasets/HuggingFaceFW/fineweb).

## Environment

The recommended Conda environment for this folder is defined in `environment.yml`.

```bash
conda env create -f environment.yml
conda activate curate_data
```

## Main files

### `curation_process.py`
Main orchestration script for the curation pipeline.

**Core responsibilities:**
- Reads the YAML configuration.
- Locates each raw source under `data_base_path`.
- Applies source-specific filtering and anonymization.
- Runs MinHash deduplication when enabled.
- Writes a per-dataset `output/00000.jsonl` file.
- Builds the combined `curated.jsonl` file and `filter_summary.json` at the curated root.

**Execution flow (`main()`):**
1. Loads `config.yaml` from the path passed with `--config`.
2. Iterates over `sources.tiktok` and `sources.youtube`.
3. Uses `cid` for YouTube inputs and `id` for TikTok inputs.
4. Runs Stage 1 filtering into `<curated_base_path>/<platform>/<method>/intermediate/`.
5. Optionally runs Stages 2-4 MinHash deduplication into `<curated_base_path>/<platform>/<method>/output/`.
6. Counts the resulting rows for each dataset.
7. Combines all outputs into one global JSONL file and writes a summary report.

**Pipeline stages:**
- Stage 1: emoji-only removal, Spanish language detection, spam heuristics, mention anonymization.
- Stage 2: MinHash signature computation.
- Stage 3: bucketization and clustering of near-duplicates.
- Stage 4: duplicate removal and final JSONL writing.

**Run (cluster launcher required):**

This pipeline must be executed via the provided SLURM launcher. Do not run `curation_process.py` directly on production or shared infrastructure — always submit the job using the launcher script so resource requests, environment activation and logging are handled consistently.

1. Create and activate the environment from `environment.yml`.
2. Edit `launcher.sbs` to set `CONDA_ENV_NAME`, `SCRIPT_PATH`, and `CONFIG_PATH` to the correct values for your environment.
3. Submit the job with `sbatch`:

```bash
sbatch launcher.sbs
```

**Expected output:**
- `<curated_base_path>/<platform>/<method>/intermediate/00000.jsonl`
- `<curated_base_path>/<platform>/<method>/removed/`
- `<curated_base_path>/<platform>/<method>/minhash/`
- `<curated_base_path>/<platform>/<method>/output/00000.jsonl`
- `<curated_base_path>/curated.jsonl`
- `<curated_base_path>/filter_summary.json`

---

### `config.yaml.example`
Template configuration file for the curation pipeline.

**Required sections:**
- `data_base_path`: Root folder that contains the raw JSONL inputs.
- `sources`: List of datasets to process, grouped by platform.
- `filter.curated_base_path`: Root folder where the curated outputs are written.
- `filter`: Thresholds for language filtering and spam heuristics.
- `minhash`: Parameters for deduplication sensitivity and bucket assignment.

**Important fields:**
- `filter.language_threshold`: Minimum fastText score for Spanish comments.
- `filter.max_urls`: Maximum number of URLs allowed in a comment.
- `filter.max_mentions`: Maximum number of `@` mentions allowed before a comment is treated as spam.
- `filter.max_repeated_seq`: Maximum length of repeated-character sequences.
- `filter.max_nonalpha_ratio`: Maximum ratio of non-alphabetic characters.
- `minhash.num_buckets`: Number of MinHash buckets. Must be compatible with `--tasks`.
- `minhash.hashes_per_bucket`: Number of hashes per bucket.

**Example usage:**
1. Copy `config.yaml.example` to `config.yaml`.
2. Fill in the raw input paths and output path.
3. Run `curation_process.py` with that config.

---

### `launcher.sbs`
Example SLURM launcher for running the pipeline on a cluster.

**What it does:**
- Requests compute resources.
- Activates the target Conda environment.
- Points to `curation_process.py` and `config.yaml`.
- Launches the curation job with `srun`.

**Typical use:**
- Duplicate the script.
- Edit the SLURM directives to match the target machine.
- Replace `CONDA_ENV_NAME`, `SCRIPT_PATH`, and `CONFIG_PATH` with real values.

---

## Curation flow

### Input
The raw inputs are JSONL files produced upstream by the collection step. The script expects one file per source and reads the identifier field automatically based on the platform:
- YouTube: `cid`
- TikTok: `id`

### Stage 1: Filtering and anonymization
The first stage reads each raw JSONL file and writes a cleaned intermediate dataset.

The filter chain is:
1. Drop comments that contain only emojis and whitespace.
2. Keep only Spanish comments using fastText language detection.
3. Remove obvious spam with heuristic rules for URLs, mentions, repeated characters, and non-alphabetic content.
4. Replace mention-like tokens such as `@name` with `@usuario`.
5. Write only `id` and `text` to the intermediate JSONL output.

This stage is designed to preserve the original text while removing noise and anonymizing users.

### Stages 2-4: MinHash deduplication
If `--no-dedup` is not used, the script applies a FineWeb-style near-duplicate removal pipeline.

1. Stage 2 computes MinHash signatures for each document and stores them under `minhash/signatures/`.
2. Stage 3 groups signatures into buckets and clusters similar documents under `minhash/buckets/` and `minhash/clusters/`.
3. Stage 4 removes duplicates by cluster membership and writes the final JSONL to `output/`.

Stage 3 is sequential by design and runs with `tasks=1` and `workers=1` inside the pipeline executor.

### Final aggregation
- After all datasets are processed, the script writes:
- `curated.jsonl`, which merges all per-dataset outputs and adds the `source` field.
- `filter_summary.json`, which records the number of kept rows per dataset and the combined total.

## Output formats

### Intermediate JSONL
Each line contains the filtered and anonymized document:
```json
{"id": "comment_id", "text": "Comment text with @usuario anonymized"}
```

### Final per-dataset JSONL
Same structure as the intermediate file, but with duplicates removed.

### Combined JSONL
The global file adds dataset metadata:
```json
{"id": "comment_id", "source": "youtube", "text": "Cleaned comment text"}
```

## Dependencies

The pipeline requires the following core packages (pins recommended):

- `datatrove[all]==0.9.0` — pipeline framework and extras (fastText, MinHash, etc.)
- `fasttext-numpy2-wheel==0.9.2` — fastText wheel compatible with older NumPy
- `numpy<2.0` — fastText is incompatible with NumPy 2.x
- `pyyaml` — configuration parsing
- `regex` — optional; improves Unicode/emoji processing

Recommended installation (Conda):
```bash
conda env create -f environment.yml
conda activate curate_data
```

Or install with `pip` into a virtualenv:
```bash
pip install 'datatrove[all]==0.9.0' pyyaml 'numpy<2' fasttext-numpy2-wheel==0.9.2 regex
```

Important: ensure `numpy` is pinned below 2.0 when using fastText (or the fasttext wheel above).

## Notes

- The script is idempotent at the file level: re-running it rewrites the target outputs.
- You can skip deduplication with `--no-dedup` if you only want the filtered intermediate data.
- The combined output is generated from the per-dataset `output/` folders, so those folders must exist for a source to appear in `curated.jsonl`.

