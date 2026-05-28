# Hate Speech Annotation and Fusion Pipeline

This directory contains the annotation and fusion workflow used to label curated hate-speech comments with multiple local LLMs and combine those annotations into a single final prediction.

The workflow has two stages:
- **Annotation (`annotate_process.py`)**: runs one or more vLLM models over an input JSONL and stores per-model annotations.
- **Fusion (`fusion_process.py`)**: loads those model annotations, builds feature vectors, applies a saved Fusion-of-Experts (FoE) artifact, and writes final predictions.

## Environment

The recommended Conda environment for this folder is defined in `environment.yml`.

```bash
conda env create -f environment.yml
conda activate annotate_data
```

## Main files

### `annotate_process.py`
Main orchestration script for model-based annotation with local vLLM backends.

**Core responsibilities:**
- Loads YAML config and prompt template.
- Reads input JSONL records with at least `id` and `text` (`source` is propagated).
- Runs structured generation constrained to two fields: `is_hate` (bool) and `explanation` (string).
- Writes append-only per-model JSONL outputs.
- Retries failed generations for a configurable number of rounds.
- Marks permanently unresolved records with `__EXHAUSTED__`.

**Execution flow (`main()`):**
1. Parses CLI arguments (`--config`, `--input-jsonl`, `--jsonl-dir`, `--only-models`, `--retry-failed-rounds`, `--log-file`).
2. Loads config and resolves `prompt_path`.
3. Resolves models from `models` (optionally filtered by `--only-models`).
4. Creates/loads per-model persistent JSONL stores.
5. Runs a main annotation pass on missing IDs.
6. Runs retry rounds on failed IDs using randomized sampling seeds.
7. Writes final `__EXHAUSTED__` markers for records that still fail after retries.

**Run (cluster launcher recommended):**

This pipeline is designed to run through the provided SLURM launcher so resource allocation and model-specific GPU requirements are handled automatically.

```bash
sbatch annotate_launcher.sbs <model_alias>
```

You can also run it directly (for local/debug scenarios):

```bash
python annotate_process.py \
	--config /path/to/annotate_config.yaml \
	--input-jsonl /path/to/curated.jsonl \
	--jsonl-dir /path/to/annotated_outputs \
	--only-models minimax_m2.5
```

**Expected output:**
- `<jsonl-dir>/<model_alias>.jsonl`
- Log file configured by `--log-file`

---

### `annotate_config.yaml.example`
Template configuration for the annotation stage.

**Required sections:**
- `prompt_path`: Markdown prompt file used for classification.
- `models`: Mapping from model alias to local model path.
- `model_params`: Base vLLM model loading arguments.
- `sampling_params`: Base generation parameters.
- `model_params_overrides`: Per-model overrides (must include `batch_size`).
- `sampling_params_overrides`: Optional per-model generation overrides.

**Important fields:**
- `model_params.tensor_parallel_size`: Base tensor parallelism for model loading.
- `model_params_overrides.<alias>.batch_size`: Required per-model pipeline batch size.
- `sampling_params.max_tokens`: Maximum generation length.
- `sampling_params.temperature`: Decoding temperature.

---

### `prompt.md`
Prompt template used during annotation.

**What it enforces:**
- Task definition for hate-speech detection.
- JSON-only response schema.
- Output fields `is_hate` and `explanation`.
- Explanation language requirement (Spanish), as defined in the prompt.

---

### `annotate_launcher.sbs`
SLURM launcher for the annotation process.

**What it does:**
- Activates the target Conda environment.
- Validates config and script paths.
- Resolves required GPU count from `tensor_parallel_size` per model alias.
- Auto-resubmits with the required `--gres=gpu:N` when needed.
- Runs `annotate_process.py` with safe defaults and logging.

**Typical use:**
- Edit placeholders (`CONDA_ENV_NAME`, `BASE_DIR`, script/config/input/output paths).
- Submit one job per model alias.

---

### `fusion_process.py`
Inference script that fuses collected model annotations using a saved FoE artifact.

**Core responsibilities:**
- Loads model artifact (`fusion_model.pkl`) and config.
- Recursively reads model annotation JSONL files under `annotated_data_folder`.
- Builds features from:
	- binary model outputs,
	- comment embeddings,
	- explanation embeddings.
- Applies optional PCA from artifact metadata when available.
- Runs FoE inference and writes final predictions as JSONL.

**Execution flow (`main()`):**
1. Loads config and resolves paths (`model_artifact`, `annotated_data_folder`, `output_jsonl`).
2. Loads collected annotations for `model_columns`.
3. Builds feature matrix from `foe_config` and `feature_meta`.
4. Loads FoE model weights from artifact payload.
5. Runs inference and computes:
	 - `foe_eval` (predicted class),
	 - `foe_score` (positive-class probability).
6. Writes merged records to `output_jsonl`.

**Run:**

```bash
python fusion_process.py --config /path/to/fusion_config.yaml
```

Optionally override artifact path via CLI:

```bash
python fusion_process.py \
	--config /path/to/fusion_config.yaml \
	--model-artifact /path/to/fusion_model.pkl
```

**Expected output:**
- `<output_jsonl>` containing fused annotations and FoE predictions.

---

### `fusion_config.yaml.example`
Template configuration for the fusion stage.

**Required sections:**
- `model_artifact`: Path to serialized FoE artifact.
- `annotated_data_folder`: Root directory with per-model annotation JSONL files.
- `output_jsonl`: Output path for fused predictions.
- `model_columns`: Model aliases used as binary annotation feature columns.
- `foe_config.input_features`: Feature toggles (binary/comment/explanation).
- `feature_meta`: Embedding processor metadata.

**Important fields:**
- `foe_config.text_column`: Preferred text column name.
- `feature_meta.comment_embeddings.model_name`: SentenceTransformer path for comment embeddings.
- `feature_meta.explanation_embeddings.columns`: Per-model explanation embedding definitions.

---

### `fusion_launcher.sbs`
SLURM launcher for fusion inference.

**What it does:**
- Activates the Conda environment.
- Resolves script and config paths.
- Runs `fusion_process.py --config <fusion_config.yaml>`.

---

### `fusion_model.pkl`
Serialized FoE model artifact used by `fusion_process.py`.

It is expected to contain model payload (architecture + weights) and, optionally, feature metadata such as PCA components for explanation embeddings.

## Annotation data flow

### Input
`annotate_process.py` expects a JSONL file where each line includes:
- `id`
- `text`
- optional `source` (preserved in outputs)

### Processing behavior
1. Sanitizes comment text for prompt safety.
2. Builds prompts from `prompt.md` via Outlines template rendering.
3. Requests structured JSON output using the `HateClass` schema.
4. Repairs malformed JSON responses when possible.
5. Stores valid predictions and retry markers in per-model JSONL.
6. Retries failed records and finally marks unresolved ones as `__EXHAUSTED__`.

### Per-model output format
Each output line contains:

```json
{
	"ts": "2026-05-28T09:30:00+00:00",
	"model_alias": "gemma_4_31B_it",
	"source": "youtube",
	"id": "comment_id",
	"text": "Original comment text",
	"is_hate": true,
	"explanation": "Justificacion en espanol"
}
```

Failed/exhausted records keep `is_hate: null` with `"__FAILED__"` or `"__EXHAUSTED__"` in `explanation`.

## Fusion data flow

### Input
`fusion_process.py` scans `annotated_data_folder` recursively for `*.jsonl` files and keeps records from the aliases listed in `model_columns`.

### Feature blocks
Depending on `foe_config.input_features`, the script can include:
1. Binary annotations from model columns (`0/1`).
2. Comment embeddings (SentenceTransformer).
3. Explanation embeddings (SentenceTransformer per model, optional PCA transform).

### Output format
The final JSONL preserves annotation columns and adds:
- `foe_eval`: fused binary prediction (`0`/`1`)
- `foe_score`: positive-class probability

## Typical workflow

1. Create and activate the environment from `environment.yml`.
2. Copy `annotate_config.yaml.example` to `annotate_config.yaml` and set real model paths.
3. Copy `fusion_config.yaml.example` to `fusion_config.yaml` and set artifact/input/output paths.
4. Edit SLURM launchers (`annotate_launcher.sbs`, `fusion_launcher.sbs`) for your cluster.
5. Run annotation jobs (one alias at a time or in parallel, depending on resources):

```bash
sbatch annotate_launcher.sbs minimax_m2.5
sbatch annotate_launcher.sbs gemma_4_31B_it
sbatch annotate_launcher.sbs apertus_it_8B
```

6. Run fusion:

```bash
sbatch fusion_launcher.sbs
```

## Dependencies

The provided `environment.yml` includes all runtime dependencies for annotation and fusion. Core packages used by scripts include:

- `vllm`
- `outlines`
- `torch`
- `pydantic`
- `json-repair`
- `pyyaml`
- `pandas`
- `numpy`
- `sentence-transformers` (required when embedding features are enabled)

## Operational notes

- Annotation outputs are append-only and index-aware: valid records are reused across reruns.
- Retry rounds are intended to recover transient generation/parsing failures.
- Fusion requires consistent `model_columns` between config and available annotated JSONL files.
- Explanations are expected in Spanish because the prompt enforces that output language.
