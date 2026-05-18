# Stance Detection Corpus — Pipeline Scripts

This folder contains the sequential scripts used to build the ALIA Stance Detection Corpus from the raw Decide Madrid open data.

The pipeline consists of **5 steps**, executed in order:

| Step | Script | Purpose |
|------|--------|---------|
| 1 | `build_corpus.py` | Build the raw corpus from Decide Madrid CSVs |
| 2 | `sampling.py` | Stratified sampling of 3,000 comments |
| 3 | `generate_blocks.py` | Generate 60 annotation blocks |
| 4 | `create_forms.gs` | Create Google Forms from blocks |
| 5 | `process_responses.py` | Process annotator responses |

---

## Prerequisites

```bash
pip install pandas openpyxl
```

---

## Step 1 — Build the raw corpus

**Script:** `build_corpus.py`

Produces `corpus_stance_madrid_recuento.csv` (~61,716 rows) from the raw Decide Madrid CSVs.

**Input (not included in repository, downloadable from [datos.madrid.es](https://datos.madrid.es)):**
- `comments.csv`
- `debates.csv`
- `proposals.csv`
- `votes.csv`

**Output:**
- `corpus_stance_madrid_recuento.csv`

**Filters applied:**
1. **First-level comments only** — Replies to other comments are excluded.
2. **Proposals with truncated titles** (>=80 chars) are excluded.
3. **Comments without text or letters** are removed.
4. **URL-only comments** (<30 chars of real text) are removed (~4,599 spam comments).
5. **Automatic welcome messages** from a bot are removed (~1,456).
6. **"Listado de Propuestas NO Repetidas"** pattern messages are removed (~709).
7. **"#TuPreguntas"** Q&A sessions with politicians are removed (~1,150).
8. **Topics without descriptions** are excluded (~9,509 comments).

**Usage:**
```bash
python build_corpus.py [path_to_raw_csvs]
```

---

## Step 2 — Stratified sampling

**Script:** `sampling.py`

Generates a stratified sample of 3,000 comments for human annotation.

**Input:**
- `corpus_stance_madrid_recuento.csv` (from Step 1)

**Output:**
- `data/corpus_final_decide_madrid.csv` (3,000 rows)

**Quality filters:**
- Comment length: 80-800 characters
- Minimum 5 words
- Topic description must have >=30 characters (excluding URLs)
- Deduplication of identical (topic, text) pairs

**Sampling strategy:**
- Only topics with >=10 quality comments are eligible
- Proportional sampling: `slots = clamp(round(n_qualifying * 0.33), min=3, max=50)`
- Length stratification within each topic (short/medium/long)
- Fixed random seed (`RANDOM_SEED = 42`) for reproducibility

**Usage:**
```bash
python sampling.py corpus_stance_madrid_recuento.csv
```

---

## Step 3 — Generate annotation blocks

**Script:** `generate_blocks.py`

Divides the 3,000 samples into 60 annotation blocks of 50 real samples + 5 gold standards each.

**Input:**
- `data/corpus_final_decide_madrid.csv`
- `annotation/gold_standard.csv`

**Output:**
- `bloques_60/bloque_01.csv` ... `bloque_60.csv`

**Gold standards:** 10 attention-check questions (GS01-GS10) with instructed-response answers. Each block includes 5 randomly selected gold standards mixed among the real samples.

**Usage:**
```bash
python generate_blocks.py
```

---

## Step 4 — Create Google Forms

**Script:** `create_forms.gs`

A Google Apps Script that automatically creates 60 Google Forms from the annotation blocks.

**What it does:**
- Creates 60 Google Forms, one per annotation block
- Each form contains 55 questions (50 real samples + 5 gold standards, shuffled)
- Three options per question: *FAVOR*, *AGAINST*, *NEUTRAL*
- An optional free-text observation field
- Embeds a completion redirect URL for Prolific

**Instructions:**
1. Upload the 60 CSVs to a Google Drive folder named `bloques_60`.
2. Open [script.google.com](https://script.google.com) and create a new project.
3. Paste this code.
4. Update `COMPLETION_URL` with your Prolific completion URL.
5. Execute the functions in batches (6 batches of 10) due to Google Apps Script's 6-minute execution limit:
   - `crearLote1()` → blocks 1-10
   - `crearLote2()` → blocks 11-20
   - ...
   - `crearLote6()` → blocks 51-60
6. Check the log (View > Logs) to obtain the form URLs.

---

## Step 5 — Process annotator responses

**Script:** `process_responses.py`

Processes the 60 Excel response files from Google Forms.

**Input:**
- `scripts/respuestas/*.xlsx` (60 response files)
- `data/corpus_final_decide_madrid.csv`
- `annotation/gold_standard.csv`

**Output:**
- `data/corpus_final_3000_anotado.csv`

**What it does:**
1. Reads all response `.xlsx` files
2. Verifies gold standards for each annotator (100% pass required)
3. Matches responses back to the original samples
4. Generates `corpus_final_3000_anotado.csv` with all 3 annotations per sample
5. Computes Fleiss' kappa and agreement statistics

**Output columns:**
- `id`, `target`, `description`, `comment`
- `anotation_1`, `anotation_2`, `anotation_3` (individual labels)
- `majority_label` (majority-vote label)
- `agreement` (`3/3`, `2/3`, or `1/3`)
- `observation_1`, `observation_2`, `observation_3` (optional annotator comments)

**Usage:**
```bash
python process_responses.py [path_to_responses_folder]
```

---

## Curation

After annotation, the final curated corpus is produced by keeping only instances with majority agreement (`2/3` or `3/3`). Instances with full disagreement (`1/1/1`, 150 instances, 5.0%) are excluded.

```python
import pandas as pd

df = pd.read_csv('data/corpus_final_3000_anotado.csv', sep=';')
df_curated = df[df['acuerdo'].isin(['2/3', '3/3'])][
    ['id', 'target', 'description', 'comment', 'majority_label']
].copy()
df_curated.rename(columns={'majority_label': 'label'}, inplace=True)
df_curated['id'] = range(1, len(df_curated) + 1)
df_curated.to_csv('data/corpus_final_curado.csv', index=False, sep=';')
```

---

## Full pipeline execution

```bash
# Step 1: Build raw corpus (~61,716 rows)
python scripts/build_corpus.py [path_to_raw_csvs]

# Step 2: Stratified sampling (3,000 rows)
python scripts/sampling.py corpus_stance_madrid_recuento.csv

# Step 3: Generate annotation blocks (60 blocks)
python scripts/generate_blocks.py

# Step 4: Create Google Forms (run in Google Apps Script)
# Open scripts/create_forms.gs in Google Apps Script and execute

# Step 5: Process responses (after annotation)
# Place response .xlsx files in scripts/respuestas/
python scripts/process_responses.py
```
