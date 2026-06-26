# DPO Pipeline — Generating Spanish Preference Pairs

Reproducible pipeline to build a **Direct Preference Optimization (DPO)** dataset from Spanish-speaking language models. The flow covers: prompt generation (Magpie + red-teaming), response generation with multiple models, comparison with an LLM judge, cleaning, auditing, and clustering.

---

## 📋 Table of Contents

- [DPO Pipeline — Generating Spanish Preference Pairs](#dpo-pipeline--generating-spanish-preference-pairs)
  - [📋 Table of Contents](#-table-of-contents)
  - [🏗️ Pipeline Architecture](#️-pipeline-architecture)
  - [✅ Prerequisites](#-prerequisites)
  - [📦 Installation](#-installation)
  - [⚙️ Configuration](#️-configuration)
  - [🚀 Step-by-Step Execution](#-step-by-step-execution)
    - [Step 1 — Prompt Generation](#step-1--prompt-generation)
    - [Step 2 — Response Generation](#step-2--response-generation)
    - [Step 3 — LLM Judge Comparison](#step-3--llm-judge-comparison)
    - [Step 4 — Cleaning and Consolidation](#step-4--cleaning-and-consolidation)
    - [Step 5 — Auditing and Clustering](#step-5--auditing-and-clustering)
      - [5.1 — Quality Auditing](#51--quality-auditing)
      - [5.2 — Prompt Clustering](#52--prompt-clustering)
  - [📁 Repository Structure](#-repository-structure)
  - [🔧 Operational Notes](#-operational-notes)

---

## 🏗️ Pipeline Architecture

```
┌────────────────────┐
│  LLM Models        │  ← OpenAI-compatible API
│  (Magpie / RT)     │
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│  1. Prompts        │  generate_prompts.py
│  (Magpie + RT)     │  → data/prompts/*.jsonl
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│  2. Responses      │  generate_responses.py (×N models)
│  (multiple models) │  → data/responses/*.jsonl
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│  3. LLM Judge      │  judge.py (model A vs model B)
│  (comparison)      │  → dpo_data/dpo_dataset_*.jsonl
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│  4. Cleaning       │  clean_dpo_data.py + strip_reasoning.py
│  (filters + dedup) │  → dpo_data/dpo_dataset_clean_merged.jsonl
│                    │  → dpo_data/dpo_dataset.jsonl (canonical, no reasoning)
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│  5. Auditing       │  audit_dpo_data.py + cluster_prompts.py
│  (QA + clustering) │  → dpo_data/audit_*.{json,csv}
└────────────────────┘
```

---

## ✅ Prerequisites

- **Python ≥ 3.13**
- Access to an **OpenAI-compatible** endpoint (vLLM, TGI, OpenAI, Azure OpenAI, etc.) for:
  - Prompt and response generation (instruction-following models)
  - LLM judge (instruction-following model; optionally with `reasoning_content`)
  - Embeddings (optional, only for `--embeddings` in auditing)
- `pip install -r requirements.txt`

---

## 📦 Installation

```bash
git clone <repo-url>
cd <repo-folder>

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

`requirements.txt` includes:

```
openai
requests
PyYAML
tqdm
rich
pandas
tenacity
pydantic
```

---

## ⚙️ Configuration

All YAML files use placeholders. **Edit the files before running**:

| File                          | What to configure                                                                                                                     |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `config_magpie.yaml`          | `model.name`, `openai.base_url`, `openai.api_key`, `magpie.*`, `paths.output_*`                                                       |
| `config_red_teaming.yaml`     | Same as Magpie, but with red-teaming templates                                                                                        |
| `config_responses.yaml`       | `model.name` (one per run), `openai.*`, `paths.input_*`, `paths.output_*`                                                             |
| `config_judge.yaml`           | `openai.*`, `judge.model` (or `null` to choose interactively), `paths.model_a_file`, `paths.model_b_file`                             |
| `config_judge_reasoning.yaml` | Same as `config_judge.yaml` + `enable_reasoning: true` and `save_reasoning: true` (for models with `reasoning_content`, e.g. kimi-k2) |
| `config_embeddings.yaml`      | `openai.*` + `embedding.model` (only if you use `--embeddings` in auditing)                                                           |

> **Tip**: export the API key as an environment variable and reference it in the YAML with `${OPENAI_API_KEY}` if your runner supports it, or replace the placeholder directly.

---

## 🚀 Step-by-Step Execution

> All commands assume you are at the repository root. The scripts use relative paths (`data/`, `dpo_data/`) that are created automatically.

### Step 1 — Prompt Generation

Generates two types of prompts:

- **Magpie**: synthetic prompts derived from the model's chat template prefix.
- **Red-teaming**: adversarial prompts designed to elicit risky responses.

```bash
# Magpie
python generate_prompts.py --config config_magpie.yaml

# Red-teaming
python generate_prompts.py --config config_red_teaming.yaml
```

**Available arguments**:

| Flag             | Default                   | Description                    |
| ---------------- | ------------------------- | ------------------------------ |
| `-c`, `--config` | `config_red_teaming.yaml` | Path to the configuration YAML |

**Output**:

```
data/prompts/magpie_prompts_<model>_<max_tokens>.jsonl
data/prompts/red_teaming_prompts_<model>_<max_tokens>.jsonl
```

---

### Step 2 — Response Generation

Run **once per model** you want to compare. Edit `config_responses.yaml` (at least `model.name` and `paths.output_file`) between runs.

```bash
python generate_responses.py --config config_responses.yaml
```

**Available arguments**:

| Flag             | Default                 | Description                    |
| ---------------- | ----------------------- | ------------------------------ |
| `-c`, `--config` | `config_responses.yaml` | Path to the configuration YAML |

**Output**:

```
data/responses/responses_<model_a>-<model_b>_<max_tokens>.jsonl
```

> The file name encodes the generator model and the model used for the prompts, which makes cross-referencing in step 3 easier.

---

### Step 3 — LLM Judge Comparison

Compares the responses of **two models** (`model_a_file` vs `model_b_file`) on the same prompt and produces `(prompt, chosen, rejected)` triples.

```bash
# Standard judge
python judge.py --config config_judge.yaml

# Judge with reasoning (models like kimi-k2, deepseek-r1, etc.)
python judge.py --config config_judge_reasoning.yaml
```

**Available arguments**:

| Flag             | Default             | Description                    |
| ---------------- | ------------------- | ------------------------------ |
| `-c`, `--config` | `config_judge.yaml` | Path to the configuration YAML |

**Output**:

```
dpo_data/dpo_dataset_<model_a>_kimi.jsonl
dpo_data/dpo_dataset_<model_a>_kimi.csv
```

> If `judge.model` is `null` in the YAML, the script lists the models available on the endpoint and lets you choose interactively.

---

### Step 4 — Cleaning and Consolidation

Merges all `dpo_dataset_*.jsonl` files in `dpo_data/`, applies quality filters, and deduplicates.

```bash
# 4.1 — Main cleaning (filters + dedup + merge)
python clean_dpo_data.py

# 4.2 — Remove residual reasoning traces (optional)
python strip_reasoning.py

# 4.3 — Regenerate CSVs from JSONL (optional)
python change_to_csv.py
```

**Arguments for `clean_dpo_data.py`**:

| Flag                                                 | Default                                   | Description                                               |
| ---------------------------------------------------- | ----------------------------------------- | --------------------------------------------------------- |
| `paths` (positional, nargs=*)                        | `[dpo_data]`                              | `.jsonl` files or directories to clean                    |
| `--output`                                           | `dpo_data/dpo_dataset_clean_merged.jsonl` | Clean dataset (with `judge_reasoning`)                    |
| `--output-csv`                                       | `dpo_data/dpo_dataset_clean_merged.csv`   | Equivalent CSV                                            |
| `--removed-output`                                   | `dpo_data/dpo_dataset_removed.jsonl`      | Removed rows                                              |
| `--removed-csv`                                      | `dpo_data/dpo_dataset_removed.csv`        | CSV of removed rows                                       |
| `--summary-csv`                                      | `dpo_data/dpo_clean_summary.csv`          | Per-file summary                                          |
| `--clean-metrics-csv`                                | `dpo_data/dpo_clean_metrics.csv`          | Filtering metrics                                         |
| `--min-rejected-tokens`                              | `20`                                      | Minimum tokens in `rejected`                              |
| `--min-length-ratio`                                 | `0.25`                                    | Minimum `chosen/rejected` ratio                           |
| `--max-length-ratio`                                 | `4.0`                                     | Maximum `chosen/rejected` ratio                           |
| `--max-chrf`                                         | `0.85`                                    | Maximum chrF between chosen/rejected (low-contrast pairs) |
| `--max-bleu`                                         | `0.60`                                    | Maximum BLEU between chosen/rejected                      |
| `--dedup-prompt` / `--no-dedup-prompt`               | `True`                                    | Deduplicate by exact prompt                               |
| `--dedup-prompt-chosen` / `--no-dedup-prompt-chosen` | `True`                                    | Deduplicate by (prompt, chosen)                           |

**Example with custom flags**:

```bash
python clean_dpo_data.py \
  --max-chrf 0.80 \
  --max-bleu 0.55 \
  --min-rejected-tokens 30 \
  --no-dedup-prompt-chosen
```

> `strip_reasoning.py` and `change_to_csv.py` do not accept arguments: they use fixed paths (`dpo_data/dpo_dataset_clean_merged.jsonl` → `dpo_data/dpo_dataset.jsonl`, the canonical lightweight alias).

---

### Step 5 — Auditing and Clustering

#### 5.1 — Quality Auditing

```bash
# Quick audit (no embeddings or near-duplicates)
python audit_dpo_data.py

# Full audit (with embeddings and near-duplicates)
python audit_dpo_data.py \
  --near-duplicates \
  --embeddings \
  --embedding-config config_embeddings.yaml \
  --write-deduped
```

**Available arguments**:

| Flag                          | Default                      | Description                               |
| ----------------------------- | ---------------------------- | ----------------------------------------- |
| `paths` (positional, nargs=*) | `[dpo_data]`                 | `.jsonl` files or directories to audit    |
| `--report`                    | `dpo_data/audit_report.json` | JSON report                               |
| `--metrics-csv`               | `dpo_data/audit_metrics.csv` | Metrics CSV                               |
| `--write-deduped`             | `False`                      | Write deduplicated JSONL files            |
| `--deduped-dir`               | `dpo_data/deduped`           | Output folder for deduplicated files      |
| `--near-duplicates`           | `False`                      | Slow `SequenceMatcher` pass               |
| `--near-duplicate-threshold`  | `0.94`                       | Similarity threshold for near-duplicates  |
| `--max-near-duplicate-bucket` | `500`                        | Skip larger length buckets                |
| `--short-rejected-tokens`     | `20`                         | Flag for short `rejected`                 |
| `--high-chrf-threshold`       | `0.85`                       | Flag for high chrF (low contrast)         |
| `--high-bleu-threshold`       | `0.60`                       | Flag for high BLEU (low contrast)         |
| `--embeddings`                | `False`                      | Compute cosine similarity with embeddings |
| `--embedding-config`          | `config_embeddings.yaml`     | Embeddings server YAML                    |
| `--high-embedding-threshold`  | `0.95`                       | Flag for high cosine similarity           |
| `--max-examples`              | `20`                         | Maximum examples per flag                 |

#### 5.2 — Prompt Clustering

Groups the prompts from the clean dataset to detect thematic domains and cluster dominance.

```bash
# Quick smoke test (1000 prompts)
python cluster_prompts.py --limit 1000

# Full run with 12 clusters
python cluster_prompts.py --k 12 --output-csv dpo_data/prompt_clusters.csv
```

**Available arguments**:

| Flag                    | Default                                   | Description                                       |
| ----------------------- | ----------------------------------------- | ------------------------------------------------- |
| `--input`               | `dpo_data/dpo_dataset_clean_merged.jsonl` | Input dataset                                     |
| `--config`              | `config_embeddings.yaml`                  | Embeddings YAML                                   |
| `--output-dir`          | `dpo_data/prompt_cluster_analysis`        | Output folder                                     |
| `--cache`               | `None`                                    | Embeddings cache (reusable)                       |
| `--output-csv`          | `None`                                    | Cluster summary CSV                               |
| `--limit`               | `None`                                    | Limit to N prompts (smoke test)                   |
| `--k`                   | `8`                                       | Number of clusters                                |
| `--max-features`        | `2500`                                    | TF-IDF terms for cluster labeling                 |
| `--min-df`              | `2`                                       | TF-IDF minimum DF                                 |
| `--max-iter`            | `25`                                      | Maximum k-means iterations                        |
| `--seed`                | `13`                                      | Random seed                                       |
| `--top-terms`           | `12`                                      | Top terms per cluster                             |
| `--samples`             | `3`                                       | Samples per cluster                               |
| `--sample-chars`        | `240`                                     | Characters per sample                             |
| `--max-scatter-points`  | `12000`                                   | Points in `cluster_scatter.svg` (0 = all)         |
| `--dominance-threshold` | `0.40`                                    | Warn if the largest cluster exceeds this fraction |

**Clustering output**:

```
dpo_data/prompt_cluster_analysis/
├── cluster_summary.csv
├── cluster_scatter.svg
├── cluster_top_terms.csv
├── prompt_clusters.csv
└── prompt_embeddings_cache.pkl
```

---

## 📁 Repository Structure

```
.
├── README.md                       # This file
├── ENTREGABLES.md                  # List of project deliverables
├── requirements.txt                # Python dependencies
│
├── config_magpie.yaml              # Magpie prompt generation config
├── config_red_teaming.yaml         # Red-teaming prompt generation config
├── config_responses.yaml           # Response generation config
├── config_judge.yaml               # LLM judge config (standard)
├── config_judge_reasoning.yaml     # LLM judge config (with reasoning)
├── config_embeddings.yaml          # Embeddings server config
│
├── generate_prompts.py             # Step 1 — prompt generation
├── generate_responses.py           # Step 2 — response generation
├── judge.py                    # Step 3 — LLM judge (AsyncOpenAI)
├── clean_dpo_data.py               # Step 4.1 — cleaning + merge
├── strip_reasoning.py       # Step 4.2 — remove reasoning traces
├── change_to_csv.py                # Step 4.3 — regenerate CSVs
├── audit_dpo_data.py               # Step 5.1 — quality auditing
└── cluster_prompts.py              # Step 5.2 — prompt clustering
```


---

## 🔧 Operational Notes

- **Concurrency**: `generate_responses.py` and `judge.py` are asynchronous (`asyncio.run`) and parallelize calls to the OpenAI-compatible endpoint. Adjust `processing.concurrency` in the YAMLs according to the server's capacity.
- **Rate limiting**: `openai.max_retries` and `openai.retry_delay` control exponential backoff on `RateLimitError` / `APIStatusError`.
- **Reasoning models**: use `config_judge_reasoning.yaml` with models that expose `reasoning_content` (kimi-k2, deepseek-r1, etc.). The field is saved in an additional column of the JSONL.
- **Reproducibility**: all scripts accept `--seed` (or read it from the YAML) so that clustering and sampling are deterministic.
- **Privacy**: the example YAMLs use placeholders (`your-openai-compatible-endpoint`, `your-api-key`, `your-model-name`). Replace them before running; **do not commit real keys**.
