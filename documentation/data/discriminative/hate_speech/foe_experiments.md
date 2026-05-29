# Fusion of Experts (FoE) Experimentation Methodology for Spanish Hate Speech Detection

This document describes the datasets used, the LLMs employed for automatic annotation, the FoE fusion methods, the experiment configuration space, and the evaluation metrics adopted in this repository.

---

## 1. Datasets and partition statistics

### 1.1 HaSCoSVA

> **Reference**: Castillo-López, G., Riabi, A., and Seddah, D. (2023). *Analyzing Zero-Shot Transfer Scenarios across Spanish Variants for Hate Speech Detection*. EACL 2023 Workshop.

**Description**: HaSCoSVa-2022 (Hate Speech Corpus with Spanish Variants) is a corpus of Spanish tweets collected using keywords related to xenophobic speech targeting immigrants. A distinguishing feature of this dataset is that it includes information about the geographic variant of Spanish (European Spanish and Latin American Spanish), which enables transfer studies across variants.

Tweets were collected via the Twitter API, applying sampling strategies by geographic regions (bounding boxes for Europe and Latin America) and keyword filtering. After an initial filtering of 75,834 tweets, 4,000 were selected for manual annotation.

**Annotation**: The process was carried out by three native Spanish annotators. The first two annotators independently labeled each tweet into three categories: xenophobic, not xenophobic, or ambiguous. A third annotator resolved disagreements and ambiguous cases. The inter-annotator agreement measured by Cohen's Kappa between the two main annotators was κ = 0.443 (88% percent agreement), considered moderate agreement according to Landis and Koch.

**Partitioning**: The process has two stages: (1) a stratified 70/30 train-test split by label; (2) from the training pool, a stratified 20% is taken for validation. This yields effective proportions of approximately 56/14/30 (train/val/test). The seed used is `RANDOM_SEED=42`.

| Partition | Samples | Hate (1) | No hate (0) | % Hate |
|-----------|--------:|--------:|-----------:|-------:|
| train     |   2,242 |     311 |     1,931 |  13.87 |
| val       |     559 |      77 |       482 |  13.77 |
| test      |   1,199 |     166 |     1,033 |  13.84 |
| **total** | **4,000** | **554** | **3,446** | **13.85** |

**Characteristics**: This is the most imbalanced dataset in the experiments, with only 13.9% positive (hate) samples. It therefore represents the most challenging scenario for detecting the minority class.

**Best reported results:**

- Comparison of monolingual vs. multilingual encoders: BETO (Spanish) outperformed mBERT (multilingual) across domains. Reported macro-F1s: BETO = **84.9** (misogyny, ±0.3) and **73.1** (immigration, ±0.8); mBERT = 74.4 (misogyny, ±7.0) and 69.6 (immigration, ±2.8).
- Variant-transfer findings (BETO): training on one regional variant and testing on another produced large drops. Example (misogyny): Train Europe → Test Europe = **89.6** (±0.6) vs Train Europe → Test LatAm = 70.5 (±0.5) — a loss of 19.1 F1 points. Similar transfer gaps appear in the immigration domain.

**Raw data & access:**

- Source and acquisition: the HaSCoSVa archive was obtained from the project's public dataset release and integrated into this repository's curated collection.
- Preprocessing and reproducibility: the original study applied hashtag segmentation and reported averaged results across five random seeds. These preprocessing choices (hashtag segmentation, URL and mention tokenization) and the use of multiple seeds can materially affect reported metrics; our runs use a fixed seed and a consistent preprocessing pipeline, which may yield slight differences versus the paper.
- Partitioning reproduced here follows the study's two-stage procedure: first a stratified 70/30 train/test split by label; then 20% of the training pool is sampled (stratified) for validation, yielding effective proportions of approximately 56% train / 14% val / 30% test.
- Regional-variant experiments (Europe vs. Latin America): to compare variants fairly the study applied random under-sampling to the larger regional subset. For the paper's balanced variant experiments the final comparable sizes were:

    | Variant | Train | Dev | Test |
    | :---: | :---: | :---: | :---: |
    | Europe | 1,400 | 350 | 750 |
    | LatAm | 840 | 210 | 450 |

- Practical note: small differences in preprocessing (e.g., hashtag segmentation) or seed choice can change reported numbers; treat the paper's reported metrics as indicative and consult the partitioning description above when reproducing experiments.

---

### 1.2 HaterNet

> **Reference**: Pereira-Kohatsu, J.C., Quijano-Sánchez, L., Liberatore, F., and Camacho-Collados, M. (2019). *Detecting and Monitoring Hate Speech in Twitter*. Sensors, 19(21), 4654.

**Description**: HaterNet is a hate speech monitoring system for Spanish on Twitter, developed in collaboration with the Secretaría de Estado de Seguridad (Spain). The corpus contains 6,000 manually labeled tweets, selected from a larger unlabelled collection of two million tweets gathered via the Twitter REST API. Tweets are in Spanish and the dataset is not split by domain or geographic variant, which differentiates it from HaSCoSVA and HatEval.

**Annotation**: Labeling was done by a panel of experts (not crowdsourcing), who manually classified tweets as hate or no-hate. Inter-annotator agreement was κ = 0.588 (σ = 0.081), considered moderate by Landis and Koch. In the paper, the authors evaluate models using 10-fold cross-validation rather than a fixed train/val/test split.

| Partition | Samples | Hate (1) | No hate (0) | % Hate |
|-----------|--------:|--------:|-----------:|-------:|
| train     |   4,199 |   1,096 |     3,103 |  26.10 |
| val       |     899 |     235 |       664 |  26.14 |
| test      |     902 |     236 |       666 |  26.16 |
| **total** | **6,000** | **1,567** | **4,433** | **26.12** |

**Best reported results:**

- The top-performing configuration combined word/emoji embeddings with TF-IDF features feeding an LSTM+MLP classifier. The reported maxima are: **AUC = 0.828** and **F1 = 0.611** (threshold 0.5).
- Production choice: the team selected a higher decision threshold (0.7) in production to favor precision (precision = 0.784, recall = 0.333, lower F1) to reduce false positives when processing large tweet volumes.
- Practical takeaway: embedding-enriched neural models consistently outperformed pure frequency-based systems on HaterNet.

**Raw data & access:**

- Source and acquisition: HaterNet was obtained from the public Zenodo release and curated into the repository.
- Corpus construction: the original collection procedure began from approximately 2 million tweets; a dictionary-based filter of hate-related terms reduced candidates to about 8,710, from which 6,000 tweets were manually annotated. The annotated set contains ~1,567 hate and ~4,433 non-hate examples (≈26% hate).
- Evaluation protocol in the paper: the canonical HaterNet evaluation reported in the literature uses 10-fold cross-validation on the 6,000 labeled tweets.
- Repository handling for FoE experiments: for workflows that require explicit train/validation/test partitions we generate a fixed stratified split (70/15/15) to enable reproducible train/val/test runs; this differs from the paper's 10-fold CV and is noted when comparing results.
- Additional methodological details: the original study performed nested validation for hyperparameter tuning (an inner 3-fold CV inside each outer fold). Frequency-based systems used LASSO-based feature selection (with leave-one-out validation to pick the penalty), while embedding-based neural models trained on the full semantic matrices.

---

### 1.3 HatEval

> **Reference**: Basile, V., Bosco, C., Fersini, E., Nozza, D., Patti, V., Rangel, F., Rosso, P., and Sanguinetti, M. (2019). *SemEval-2019 Task 5: Multilingual Detection of Hate Speech Against Immigrants and Women in Twitter*. Proceedings of SemEval-2019, 54–63.

**Description**: HatEval is the dataset from SemEval-2019 Task 5, a shared task for multilingual detection of hate speech in Twitter. The corpus covers two languages (English and Spanish) and two target groups: immigrants and women. This repository uses only the **Spanish** partition.

The Spanish dataset contains 6,600 tweets in total (5,000 for training+development and 1,600 for test), of which 3,209 target women and 1,991 target immigrants. Tweets were collected between July and September 2018 (with tweets against women partially coming from earlier challenges such as AMI 2018).

The task is split into two subtasks:
- **Subtask A**: Binary classification — hate speech detection (0/1). This is the subtask directly comparable with the other datasets in the repository.
- **Subtask B**: Fine-grained classification — target type (individual vs. group) and aggressiveness of the speaker.

**Annotation**: Annotation was performed using the Figure Eight (F8) crowdsourcing platform. At least three independent judgments per tweet were collected, with the final label assigned by relative majority. Additionally, two expert annotators (native or near-native Castilian Spanish speakers experienced in the task) validated the annotations; the final label was assigned by majority vote among the crowd and the two experts. The average confidence reported by F8 for the HS field in the Spanish dataset was 0.89. The data was distributed such that the hate class is over-represented relative to its natural frequency on Twitter to facilitate supervised learning.

**Partitioning**: The train/dev/test splits come directly from the official SemEval-2019 shared task files.

| Partition | Samples | Hate (1) | No hate (0) | % Hate |
|-----------|--------:|--------:|-----------:|-------:|
| train     |   4,500 |   1,857 |     2,643 |  41.27 |
| val       |     500 |     222 |       278 |  44.40 |
| test      |   1,599 |     660 |       939 |  41.28 |
| **total** | **6,599** | **2,739** | **3,860** | **41.51** |

**Best reported results:**

- SemEval-2019 highlights:
      - Subtask A (binary hate detection): best Spanish systems (Atalaya / MineriaUNAM) reached **F1 = 0.730**; best English system (Fermi) reached **F1 = 0.651**.
      - Subtask B (fine-grained labels): best Spanish system achieved **Exact Match Ratio = 0.705**; best English system reached 0.570.
      - The competition included 74 teams and many feature-engineered SVM systems; linear SVMs with rich linguistic features were particularly effective for Spanish.

**Raw data & access:**

- Source and acquisition: HatEval is the SemEval-2019 Task 5 release for hate speech detection; the Spanish partition is included in the official task files.
- Composition and splitting: the Spanish subset contains 5,000 train/dev and 1,600 test examples. The task authors intentionally over-sampled hate examples to create a more balanced supervised dataset; the Spanish test partition contains 660 hate and 940 non-hate instances.

---

### 1.4 MTLHate

> **Reference**: Pan, R., García-Díaz, J.A., and Valencia-García, R. (2025). *Spanish MTLHateCorpus 2023: Multi-task learning for hate speech detection to identify speech type, target, target group and intensity*. Computer Standards & Interfaces, 94, 103990.

**Description**: The MTLHateCorpus 2023 (Multi-Task Learning Hate Corpus) is a corpus of Spanish tweets annotated for four simultaneous subtasks related to hate speech:

1. **Type**: the nature of the speech — hate, hope, or offensive. A multiclass classification task.
2. **Target**: whether the speech is aimed at an individual or a group. Binary classification.
3. **Group**: identification of the target group (racism, homophobia, misogyny, aporophobia, ableism, fatphobia, transphobia, work-related). A multi-label task.
4. **Intensity**: severity of the speech on a six-level Babak Bahador scale (from mild disagreement to calls for death). An ordinal classification task.

**Annotation**: Overall inter-annotator agreement was κ = 0.349, considered low, mainly due to discrepancies in the `none` label. Removing those cases raised agreement significantly to κ = 0.513.

**Partitioning**: The original corpus includes a `__split` column with the authors' predefined train/val/test assignment (stratified by the *type* subtask with proportions 75/15/15). Experiments preserve this original assignment and filters examples whose `label` column is `hate` or `none` (i.e., it excludes examples labeled `hope` or `offensive` that are not directly comparable with the repository's binary scheme).

| Partition | Samples | Hate (1) | No hate (0) | % Hate |
|-----------|--------:|--------:|-----------:|-------:|
| train     |  15,964 |  8,419 |   7,545 |  52.74 |
| val       |   3,421 |  1,804 |   1,617 |  52.73 |
| test      |   3,422 |  1,805 |   1,617 |  52.75 |
| **total** | **22,807** | **12,028** | **10,779** | **52.74** |

**Best reported results:**

- The MTLHate study reports results across four subtasks using three families of strategies: Zero-Shot LLMs, fine-tuning single-task models, and multi-task learning (MTL). Best highlights:
      - Speech-type (hate/hope/offensive/none): the top single-system F1 (fine-tuned) was ≈62.37 (XLM-T); an ensemble mode reached **F1 ≈ 63.35**.
      - Target type (individual vs. group): fine-tuned systems reached ~69.7 F1 (XLM-T/MarIA), while an ensemble reached **F1 ≈ 71.09**.
      - Targeted-group (multi-label): MarIA and mBART (MTL) stood out; best reported single-system F1 ≈ **63.97** (MarIA), while MTL mBART achieved **F1 ≈ 62.91** with superior recall.
      - Intensity (6-level ordinal): the ensemble and fine-tuned BETO achieved the top F1s (ensemble ≈ **48.63**, BETO ≈ **48.65**).

**Raw data & access:**

- Source and acquisition: the official MTLHateCorpus release contains approximately 35,473 annotated messages and was provided to this project by the dataset authors.
- Published splits and counts: the release reports roughly 24,829 training, 5,321 validation, and 5,323 test instances (total ≈35,473).
- Reproducibility: when the authors' original split labels are available they are preserved; otherwise we recreate train/validation/test partitions via stratified sampling on the `type` label to preserve class proportions across splits.
- Test split is not directly comparable with experiments from this repository work.

---

### Comparative summary

| Dataset   | Total   | Language | Platform | Source       | % Hate | Baseline (F1-macro) | Baseline source |
|-----------|--------:|---------:|---------:|-------------:|-------:|--------------------:|----------------:|
| HaSCoSVA  |   4,000 | es      | Twitter  | Castillo-López et al., 2023 | 13.85% | 0.731 (BETO, xenophobia) | HaSCoSVA paper, Table 2 |
| HaterNet  |   6,000 | es      | Twitter  | Pereira-Kohatsu et al., 2019 | 26.12% | 0.611 (LSTM+MLP+TF-IDF, F1@0.5) | HaterNet paper, Table 6 (primary AUC = 0.828) |
| HatEval   |   6,599 | es      | Twitter  | Basile et al., 2019 (SemEval) | 41.51% | 0.730 (linear SVM, Atalaya/MineriaUNAM) | HatEval paper, Subtask A ES stats |
| MTLHate   |  22,807 | es      | Twitter  | Pan et al., 2025 | 52.74% | — (no comparable binary baseline) | — |

---

## 2. LLMs used for annotation and generation parameters

Automatic dataset annotation is performed by the script as follows:

- Uses local `vLLM` checkpoints via an `outlines` offline wrapper (`VLLMOffline`) to perform batched GPU inference.
- Enforces a `Pydantic` output schema `HateClass` with two fields: `is_hate` (bool) and `explanation` (str). Parsing uses `json_repair` to tolerate minor generation issues.
- Storage model: per-model append-only JSONL files are the source of truth (one JSONL per model alias). CSV split files are read-only and used only to obtain `(id, text)` pairs.
- Idempotency and retries:
      - Rows already annotated (valid `is_hate` boolean) are skipped.
      - Failed generations are represented with `__FAILED__` and retried up to `--retry-failed-rounds` times; before each retry the script removes the previous FAILED records from the JSONL to avoid duplicates.
      - Permanently exhausted entries are rewritten with `explanation = __EXHAUSTED__` while keeping `is_hate = null`.
- Batch handling: comments are sanitized to avoid JSON-breaking characters, prompts are adapted to the tokenizer/chat template when available, and `generate_batch` is used with `SamplingParams`; a per-model `batch_size` is read from the config overrides.
- Logging and robustness: results are appended to JSONL immediately as each batch completes; failed batches fall back to per-item attempts; the script loads each model once and iterates all prompts and splits to minimize load/unload overhead.
- CLI highlights: `--jsonl-dir` (required), `--config` (default `scripts/datasets/gold_standard/annotation/config_vllm_curated.yaml`), `--only-models`, `--only-prompts`, `--only-datasets`, `--text-column` (default `comment`), and `--retry-failed-rounds` (default 5).

### 2.1 Prompting stage and strategy

A **few shot** prompting strategy is used for synthetic annotations. The model acts as an expert content moderator specialized in detecting hate speech on social media during periods of social tension in Spain. The operational definition of hate speech includes explicit criteria such as incitement to violence, dehumanization of vulnerable groups, calls for discrimination, glorification of violent acts, extremist rhetoric, and promotion of negative stereotypes — both explicit and implicit or in sarcastic form. Political criticism, satire, generic expressions of frustration without a specific group target, and factual information are explicitly excluded.

### 2.2 Configured models

The annotation pipeline loads model aliases from configuration. Current model aliases (keys in `models`) include:

| Internal ID | Hugging Face Model ID | License |
|-------------|------------------------:|---------------|
| `apertus_it_8B` | [swiss-ai/Apertus-8B-Instruct-2509](https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509) | [apache-2.0](https://huggingface.co/datasets/choosealicense/licenses/blob/main/markdown/apache-2.0.md) |
| `gemma_4_31B_it` | [google/gemma-4-31B-it](https://huggingface.co/google/gemma-4-31B-it) | [apache-2.0](https://ai.google.dev/gemma/apache_2) |
| `minimax_m2.5` | [MiniMaxAI/MiniMax-M2.5](https://huggingface.co/MiniMaxAI/MiniMax-M2.5) | [modified-mit](https://github.com/MiniMax-AI/MiniMax-M2.5/blob/main/LICENSE-MODEL) |
| `mistral_7b_instruct_v0.3` | [mistralai/Mistral-7B-Instruct-v0.3](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3) | [apache-2.0](https://huggingface.co/datasets/choosealicense/licenses/blob/main/markdown/apache-2.0.md) |
| `phi_4` | [microsoft/phi-4](https://huggingface.co/microsoft/phi-4) | [mit](https://huggingface.co/api/resolve-cache/models/microsoft/phi-4/932b33c0ec9ca189badeb22480721a8de9d0e006/LICENSE?%2Fmicrosoft%2Fphi-4%2Fresolve%2Fmain%2FLICENSE=&etag=%22700edcc5f42c4816520bc554926ad7e0d9e613d7%22) |

### 2.3 Sampling parameters

The default sampling parameters used when invoking `vLLM` are read from `sampling_params` in the config:

| Parameter | Config value |
|-----------|-------------:|
| `max_tokens` | 1024 |
| `temperature` | 0.15 |
| `top_p` | 0.90 |
| `seed` | 42 |

Per-model sampling overrides can be provided via `sampling_params_overrides` in configuration.

### 2.4 Runtime & model-load parameters

Model loading and runtime defaults are taken from `model_params` in the config. Key values:

| Parameter | Config value |
|-----------|-------------:|
| `max_model_len` | 8192 |
| `tensor_parallel_size` | 1 (default; per-model overrides available) |
| `gpu_memory_utilization` | 0.90 |
| `dtype` | bfloat16 |
| `seed` | 42 |
| `enforce_eager` | true |

**Notes:**

- Experiments use specific per-model `batch_size` in `model_params_overrides` for each alias.
- Experiments apply `rope_scaling` compatibility fixes when required and may retry model initialization with `tokenizer_mode=slow` on tokenizer errors.
- To limit memory pressure the configuration also exposes `max_model_len` and `gpu_memory_utilization` tuning knobs; adjust per-cluster/HW profile as needed.

---

## 3. Fusion methods

### 3.1 Fusion of Experts (FoE) — reference method

> **Inspiration reference**: Wang, H., Polo, F.M., et al. (2024). *Fusing Models with Complementary Expertise*. ICLR 2024.

**Paper idea**: FoE addresses the problem of combining outputs from several expert models with complementary expertise — i.e., models specialized on different domains or subpopulations, so that none is individually optimal across all data. The reference paper covers both discriminative tasks (classification) and generative tasks (LLM text generation). **In this repository we focus exclusively on classification** (Section 3.2 of the paper), where experts output predictions over discrete classes. Unlike classical ensembles (averaging outputs), FoE frames the problem as supervised learning: a lightweight fusion model (the fuser) is trained to select or combine expert continuous predictions using validation data.

**Key difference with the original paper**: The original experts are fine-tuned models specialized on particular domains. In this repository, experts are **general-purpose LLMs** (Mistral, Phi-4, Apertus) that are prompted to perform hate speech classification without domain fine-tuning. Knowledge comes from model pretraining rather than supervised specialization.

**Classification mechanism**: Given K expert models $f_1, ..., f_K$, the representation of an input $x$ is the concatenation of their predictions: $f(x) = [f_1(x), ..., f_K(x)]$. The fuser $F_\theta$ is trained by minimizing cross-entropy loss over that concatenated representation:

$$\min_\theta \sum_k \sum_i \ell(F_\theta(f(x_i^k)), y_i^k)$$

where $F_\theta$ can be a small fully connected neural network.

**Adaptation in this repository**: Experiments' implementation adapts this mechanism to hate speech detection with LLM experts. Instead of classifier probabilities, experts provide **binary annotations**. This simplifies the fuser input vector while preserving the core idea: the fusion classifier learns to optimally combine expert judgements.

---

### 3.2 Experiments' extended method from FoE

Experiments from this work extend FoE by incorporating **semantic text representations** as additional feature levels beyond binary annotations.

**Theoretical basis**: Experiments' methodology is inspired by Section 3.3 (Fusion of Generative Experts) of the reference paper (Wang et al., ICLR 2024). That section proposes that, when **experts are generative LLMs**, instead of concatenating their textual outputs one can concatenate transformer final-layer embeddings of the input and generated text. Those embeddings are informative for selecting the most suitable expert. The paper validates this idea on sentiment analysis (Section 5.2) using domain-fine-tuned models as experts; the fusion classifier ingests concatenated expert embeddings **to select the correct expert**, reaching 99.1% accuracy in expert selection. See the reference repo: https://github.com/hwang595/FoE-ICLR2024/blob/main/lm_experiments/utils.py.

Experiments' methodology adapts this to hate speech classification: instead of extracting final-layer embeddings from LLM experts (expensive), we use as embeddings from comments as embeddings from explanation texts generated by each LLM as a semantic representation of its reasoning. The fuser input vector can concatenate up to three levels:

```
Level 1: Binary annotations
├─ Predictions from each LLM-expert
└─ Each feature is 0 or 1

Level 2: Comment embeddings
├─ SentenceTransformer: dense vector (configured model: paraphrase-multilingual-MiniLM-L12-v2)
└─ TF-IDF: sparse vector (up to 5,000 features, n-grams/bigrams enabled in the cache pipeline)

Level 3: Explanation embeddings
├─ Embeddings of the textual explanation generated by each LLM-expert
├─ Stacked horizontally across experts
└─ Optional dimensionality reduction via PCA (default: 128 components)
```

The final input to the fusion classifier is the concatenation of the active levels. Each level can be enabled via the flags `binary_annotations`, `comment_embeddings`, and `explanation_embeddings` in configuration files.

---

### 3.3 Fusion classifier architectures

The fusion module is a lightweight PyTorch neural network trained on the FoE feature vector. Three variants are implemented:

#### `mlp` — reference MLP
A single-hidden-layer MLP. Architecture:

```
Input → Linear(input_dim, hidden_dim) → ReLU → Linear(hidden_dim, 2) → LogSoftmax
```

- **default hidden_dim**: 64
- Minimal design used as a baseline.
- **Original reference**: `mlp.py` in hwang595/FoE-ICLR2024.

#### `sentiment_mlp` — two-layer MLP with dropout
A two-hidden-layer MLP with dropout, adapted from the sentiment experiment architecture in the original FoE paper. Architecture:

```
Input → Linear(input_dim, hidden_dim) → ReLU → Dropout(p)
      → Linear(hidden_dim, hidden_dim) → ReLU → Dropout(p)
      → Linear(hidden_dim, 2) → LogSoftmax
```

- **default hidden_dim**: 1024
- **default dropout**: 0.5
- Designed for high-dimensional inputs (concatenated embeddings from multiple LLMs).

#### `mlp_v2` — improved MLP with funneling
A two-hidden-layer MLP with progressive dimensionality reduction and dropout. Architecture:

```
Input → Linear(input_dim, hidden_dim) → ReLU → Dropout(dropout)
      → Linear(hidden_dim, hidden_dim//2) → ReLU → Dropout(dropout)
      → Linear(hidden_dim//2, 2) → LogSoftmax
```

- **default hidden_dim**: 64 (mid_dim = hidden_dim // 2 = 32)
- **default dropout**: 0.3
- Adds regularization via dropout on both layers to improve generalization when many features are active.

**Common training**: All three architectures are trained with Adam (`lr=0.001`, `weight_decay=1e-4`), NLLLoss, up to 100 epochs, `batch_size=64`, `random_state=42`, and early stopping/model selection by `selection_metric=f1_macro`. The best model state (by test metric) is saved.

---

## 4. Experiment configuration space

Experiment orchestration is defined as a parameter combination over a shared base setup plus per-run overrides.

In practice, each run is created by combining:

- a dataset-specific split assignment (train/val/test),
- a selected expert set (model + prompt pairing),
- a feature mask (`binary_annotations`, `comment_embeddings`, `explanation_embeddings`),
- one embedding method (`sentence_transformer` or `tfidf`), and
- one fusion architecture (`mlp`, `sentiment_mlp`, or `mlp_v2`).

Each run explores all non-empty combinations across these axes:

### 4.1 Inputs (feature levels)

All non-empty combinations of three input levels are evaluated:

- `binary_annotations` — binary annotations from LLM experts (Level 1)
- `comment_embeddings` — embedding of the comment text (Level 2)
- `explanation_embeddings` — embeddings of explanations by each expert (Level 3)

This yields 7 possibilities (2^3 − 1): annotations only, comments only, explanations only, annotations + comments, annotations + explanations, comments + explanations, and all three together.

### 4.2 Fusion architectures

The three fusion classifier architectures described above are evaluated:

- `mlp` — reference [MLP](https://github.com/hwang595/FoE-ICLR2024/blob/main/mlp.py)
- `sentiment_mlp` — two-layer high-capacity [MLP](https://github.com/hwang595/FoE-ICLR2024/blob/main/lm_experiments/utils.py#L47) with dropout
- `mlp_v2` — improved funnel MLP with moderate dropout

### 4.3 Embedding computation methods

For levels that require vector representations (Level 2 and Level 3), two methods are evaluated:

**`sentence_transformer`**:
- Model from config: `paraphrase-multilingual-MiniLM-L12-v2`
- Dense embeddings for comments and per-model explanations
- PCA controlled by configuration parameter (default: 128) for explanation-feature reduction in the training pipeline
- Embeddings are cached to disk in configuration specific path

**`tfidf`**:
- Vectorizer: TF-IDF with n-grams/bigrams, up to **2000 features** by configuration
- Faster and CPU-only, but less semantically rich
- PCA is not applied during cache generation; dimensionality reduction is applied at training time when configured

### 4.4 LLM experts referenced in experiments

The active expert model aliases are:

- `mistral_7b_instruct_v0.3`
- `phi_4`
- `apertus_it_8B`
- `gemma_4_31B_it`
- `minimax_m2.5`

In the experiments, this means evaluating different model concatenations in the fusion input (all subsets of experts with size >= 2), always under the same **few shot** prompt. With 5 available models, the explored concatenations cover sizes 2, 3, 4, and 5 (e.g., pairwise combinations, 3-model combinations, etc.), yielding `2^5 - 1 - 5 = 26` total model combinations.

### 4.5 Total search space

The Cartesian product of axes in the current config yields the following search space per dataset:

| Axis | Options |
|-----:|--------:|
| Model-prompt combinations | 26 |
| Input combinations | 7 |
| Architectures | 3 |
| Embedding methods | 2 |
| **Total experiments per dataset** | **1,092** |

Each experiment run stored its metrics in the configured output logs for later aggregation and ranking against baselines.

---

## 5. Evaluation metrics

### 5.1 Primary metric: F1-macro

The primary metric used for model selection (early stopping on validation) and experiment comparison is **F1-macro**:

$$F1\text{-macro} = \frac{1}{C} \sum_{c=1}^{C} F1_c = \frac{1}{C} \sum_{c=1}^{C} \frac{2 \cdot P_c \cdot R_c}{P_c + R_c}$$

where C is the number of classes (2 in our binary experiments). F1-macro gives equal weight to both classes regardless of class frequency, making it robust under class imbalance.

### 5.2 Additional metrics

#### Cohen's Kappa (κ)

$$\kappa = \frac{p_o - p_e}{1 - p_e}$$

where $p_o$ is observed agreement and $p_e$ is expected agreement by chance. Cohen's Kappa measures concordance between two annotators (these can be human annotators or single-system outputs such as an LLM), accounting for chance agreement. It is appropriate when comparing a single system's predictions to one human annotator or when assessing agreement between any two annotators.

#### Fleiss' Kappa (κ_F)

Fleiss' Kappa generalizes Cohen's Kappa to the case of any number of raters assigning categorical labels to a fixed set of items. It compares the observed proportion of agreement to the agreement expected by chance across the rater population. For a binary task the statistic can be written as:

$$\kappa_F = \frac{\overline{P} - \overline{P_e}}{1 - \overline{P_e}}$$

where $\overline{P}$ is the mean of per-item agreement proportions and $\overline{P_e} = \sum_j p_j^2$ is the chance agreement computed from the marginal proportion $p_j$ of assignments to category $j$. Fleiss' Kappa is useful to report when evaluating agreement across multiple annotators or expert models (for example when many LLMs vote or when human crowds produce multiple labels).

#### Accuracy

$$\text{Accuracy} = \frac{TP + TN}{TP + TN + FP + FN}$$

Measures the percentage of correct predictions overall. Although intuitive, accuracy can be misleading under class imbalance. Hence it is reported complementarily to F1-macro, not as the primary metric.

---

## 6. Methodology evaluation results

The results below correspond to last experiment runs over the test partitions of each dataset. They are now ordered from the simplest baselines to the fusion experiments: individual LLMs, majority vote, and then FoE. The individual-model and majority-vote blocks are the first comparison point before introducing fusion.

Table columns:

- **Models**: number of LLM experts combined (from 2 to 5)
- **Inputs**: active feature levels (`bin` = binary annotations, `com` = comment embeddings, `exp` = explanation embeddings)
- **Emb. method**: embedding computation method (`tfidf` or `sentence_transformer`)
- **Architecture**: fusion classifier architecture
- **F1-macro**: primary metric
- **Kappa**: Cohen's Kappa
- **Accuracy**: overall accuracy
- **Δ baseline**: difference relative to the reference baseline F1-macro

---

### 6.1 Target baseline scores (paper references)

This subsection lists our reference baseline scores from best F1 macro score reported in each dataset's original paper. These target numbers are the comparison points used throughout Section 6 when reporting Δ relative to literature SOTA. When a direct comparison is not possible the entry is marked as N/A with an explanation.

| Dataset | Reference (best reported) | F1-macro | Notes |
|--------:|:-------------------------|---------:|:-----|
| HaSCoSVA | BETO (Castillo-López et al., 2023) | 0.731 | Reported for immigration xenophobia; authors averaged multiple runs and applied hashtag segmentation (see Section 1.1 for comparability notes).
| HatEval | improved SVM (Atalaya / MineriaUNAM, SemEval-2019 Subtask A) | 0.730 | Official SemEval-2019 Spanish Subtask A best F1; our partitioning is identical to the shared task.
| HaterNet | LSTM+MLP (+TF-IDF) (Pereira-Kohatsu et al., 2019) | 0.611 | Paper reports best F1 under 10-fold CV; our static split differs so comparisons are indicative.
| MTLHate | — | N/A | MTLHate reports multi-task metrics (multi-class / multi-label / ordinal) not directly comparable or extrapolable to the binary hate/not-hate evaluation used in this repository; therefore no direct baseline is provided.

### 6.2 Individual LLMs

These results summarize the standalone performance of each LLM under the few-shot prompting strategy, before any fusion step. The table below includes the reference baseline from Section 6.1 and the difference Δ (model F1 − reference F1).

| Dataset | Best by F1-macro and Kappa | F1-macro | Baseline (Sec. 6.1) | Δ baseline | Kappa |
|--------:|:-----------------|---------:|:------------------:|----------:|------:|
| HaSCoSVA | gemma_4_31B_it | 0.778767 | 0.731 | +0.0478 | 0.559131 |
| HatEval | apertus_it_8B | 0.659749 | 0.730 | -0.0703 | 0.337292 |
| HaterNet | apertus_it_8B | 0.683382 | 0.611 | +0.0724 | 0.387919 |
| MTLHate | apertus_it_8B | 0.707625 | N/A | N/A | 0.415638 |

Δ baseline is computed as `F1_model - F1_reference` (Section 6.1). 'N/A' indicates no directly comparable baseline is available in the literature.

### 6.3 Majority vote ensemble

The majority-vote ensemble combines the individual LLM predictions and ranks the resulting model mixtures by F1-macro, tie-broken by Cohen's Kappa. Each dataset below explored 16 valid few shot combinations.

| Dataset | Best by F1-macro | F1-macro | Baseline (Sec. 6.1) | Δ baseline | Kappa | Fleiss Kappa |
|--------:|:-----------------|---------:|:------------------:|----------:|------:|-------------:|
| HaSCoSVA | apertus_it_8B + gemma_4_31B_it + minimax_m2.5 + phi_4 | 0.771962 | 0.731 | +0.0410 | 0.546548 | 0.590152 |
| HatEval | apertus_it_8B + mistral_7b_instruct_v0.3 + phi_4 | 0.647385 | 0.730 | -0.0826 | 0.297720 | 0.372547 |
| HaterNet | apertus_it_8B + gemma_4_31B_it + mistral_7b_instruct_v0.3 + phi_4 | 0.708516 | 0.611 | +0.0975 | 0.424004 | 0.316058 |
| MTLHate | apertus_it_8B + gemma_4_31B_it + mistral_7b_instruct_v0.3 + phi_4 | 0.705131 | N/A | N/A | 0.410568 | 0.386045 |

Δ baseline is computed as `F1_model - F1_reference` (Section 6.1). 'N/A' indicates no directly comparable baseline is available in the literature.

The next subsections keep the FoE-based results for reference, but they now sit after the non-fusion baselines.

### 6.4 Fusion of Experts in HaSCoSVA

> **Partial comparability**: The paper baseline (BETO, F1-macro = 0.731) was obtained by averaging multiple runs and applying hashtag segmentation before splitting; our reproduction uses a single fixed split (`RANDOM_SEED=42`) without hashtag segmentation. Results below are therefore indicative but not strictly identical to the paper.

| Rank | Models | Inputs | Emb. method | Architecture | F1-macro | Kappa | Accuracy | Δ baseline |
|-----:|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | BETO | — | — | — | 0.7310 | — | — | 0.0000 |
| 1 | **mistral_7b_instruct_v0.3 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5** | **binary_annotations + comment_embeddings + explanation_embeddings** | **tfidf** | **sentiment_mlp** | **0.8166** | **0.6331** | 0.9116 | +0.0856 |
| 2 | mistral_7b_instruct_v0.3 + phi_4 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5 | comment_embeddings + explanation_embeddings | tfidf | mlp | 0.8163 | 0.6327 | 0.9133 | +0.0853 |
| 3 | gemma_4_31B_it + minimax_m2.5 | binary_annotations + explanation_embeddings | tfidf | mlp | 0.8147 | 0.6294 | 0.9116 | +0.0837 |
| 4 | mistral_7b_instruct_v0.3 + phi_4 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5 | binary_annotations + comment_embeddings + explanation_embeddings | tfidf | sentiment_mlp | 0.8128 | 0.6256 | 0.9116 | +0.0818 |
| 5 | phi_4 + gemma_4_31B_it | binary_annotations + comment_embeddings + explanation_embeddings | tfidf | sentiment_mlp | 0.8128 | 0.6257 | **0.9141** | +0.0818 |

---

### 6.5 Fusion of Experts in HatEval

> **Direct comparability**: Results use the official SemEval-2019 splits and are directly comparable with the reference baseline (linear SVM, F1-macro = 0.73).

| Rank | Models | Inputs | Emb. method | Architecture | F1-macro | Kappa | Accuracy | Δ baseline |
|-----:|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | improved SVM | — | — | — | 0.7300 | — | — | 0.0000 |
| 1 | **phi_4 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5** | **comment_embeddings + explanation_embeddings** | **tfidf** | **sentiment_mlp** | **0.8048** | **0.6111** | **0.8074** | +0.0748 |
| 2 | phi_4 + apertus_it_8B + gemma_4_31B_it | binary_annotations + comment_embeddings + explanation_embeddings | tfidf | mlp | 0.8046 | 0.6104 | **0.8074** | +0.0746 |
| 3 | mistral_7b_instruct_v0.3 + phi_4 + apertus_it_8B + gemma_4_31B_it | comment_embeddings + explanation_embeddings | tfidf | mlp_v2 | 0.8033 | 0.6079 | 0.8061 | +0.0733 |
| 4 | mistral_7b_instruct_v0.3 + gemma_4_31B_it + minimax_m2.5 | binary_annotations + comment_embeddings + explanation_embeddings | tfidf | mlp | 0.8031 | 0.6073 | 0.8061 | +0.0731 |
| 5 | phi_4 + apertus_it_8B + gemma_4_31B_it | comment_embeddings + explanation_embeddings | tfidf | sentiment_mlp | 0.8027 | 0.6067 | 0.8055 | +0.0727 |

---

### 6.6 Fusion of Experts in HaterNet

> **Relative comparability**: HaterNet's paper reports 10-fold CV; our runs use a single stratified split (70/15/15, `RANDOM_SEED=42`) with a test set of **902** samples. Reported improvements are relative to the paper baseline.

| Rank | Models | Inputs | Emb. method | Architecture | F1-macro | Kappa | Accuracy | Δ baseline |
|-----:|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | LSTM+MLP+TF-IDF | — | — | — | 0.6110 | — | — | 0.0000 |
| 1 | **mistral_7b_instruct_v0.3 + gemma_4_31B_it + minimax_m2.5** | **binary_annotations + comment_embeddings + explanation_embeddings** | **tfidf** | **sentiment_mlp** | **0.8417** | **0.6837**| **0.8825** | +0.2307 |
| 2 | mistral_7b_instruct_v0.3 + gemma_4_31B_it + minimax_m2.5 | binary_annotations + comment_embeddings + explanation_embeddings | tfidf | mlp_v2 | 0.8387 | 0.6778 | 0.8803 | +0.2277 |
| 3 | mistral_7b_instruct_v0.3 + gemma_4_31B_it + minimax_m2.5 | comment_embeddings + explanation_embeddings | tfidf | mlp_v2 | 0.8377 | 0.6759 | 0.8803 | +0.2267 |
| 4 | mistral_7b_instruct_v0.3 + gemma_4_31B_it + minimax_m2.5 | binary_annotations + explanation_embeddings | tfidf | sentiment_mlp | 0.8374 | 0.6748 | 0.8769 | +0.2264 |
| 5 | mistral_7b_instruct_v0.3 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5 | binary_annotations + comment_embeddings + explanation_embeddings | tfidf | mlp | 0.8372 | 0.6746 | 0.8780 | +0.2262 |

---

### 6.7 Fusion of Experts in MTLHate

> **No comparability**: MTLHate's paper reports multi-task metrics (multi-class / multi-label / ordinal) not directly comparable or extrapolable to the binary hate/not-hate evaluation used in this repository; therefore no direct baseline is provided.

| Rank | Models | Inputs | Emb. method | Architecture | F1-macro | Kappa | Accuracy |
|-----:|---|---:|---:|---:|---:|---:|---:|
| 1 | **mistral_7b_instruct_v0.3 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5** | **comment_embeddings + explanation_embeddings** | **sentence_transformer** | **sentiment_mlp** | **0.8273** | **0.6547** | **0.8282** |
| 2 | **phi_4 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5** | **comment_embeddings + explanation_embeddings** | **sentence_transformer** | **mlp_v2** | **0.8273** | **0.6547** | **0.8282** |
| 3 | mistral_7b_instruct_v0.3 + phi_4 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5 | comment_embeddings + explanation_embeddings | sentence_transformer | mlp_v2 | 0.8257 | 0.6515 | 0.8261 |
| 4 | mistral_7b_instruct_v0.3 + gemma_4_31B_it + minimax_m2.5 | binary_annotations + comment_embeddings + explanation_embeddings | sentence_transformer | mlp | 0.8257 | 0.6516 | 0.8267 |
| 5 | mistral_7b_instruct_v0.3 + phi_4 + apertus_it_8B + gemma_4_31B_it + minimax_m2.5 | comment_embeddings + explanation_embeddings | sentence_transformer | mlp | 0.8252 | 0.6504 | 0.8255 |

### 7. Analysis and observations from results

Overall, FoE is the strongest strategy for annotating these hate speech corpora. Compared with the best individual model and majority vote, it consistently improves discriminative performance and, when the metric is available, also improves agreement and accuracy. The gain is especially clear on HatEval, HaterNet, and MTLHate, and it remains strong on HaSCoSVA despite being the most imbalanced dataset.

The operational reading is straightforward: individual models provide a useful signal, majority vote partially stabilizes the decision, but the fuser learns to exploit the complementarity between experts and between representation levels more effectively. Therefore, for automatic annotation, FoE is more suitable than a naive majority aggregation.

| Dataset | Baseline / Best reported F1_macro | Best Individual LLM F1_macro | Best Individual LLM Kappa | Best Majority Vote F1_macro | Best Majority Vote Kappa | Best Majority Vote Fleiss Kappa | Best FoE F1_macro | Best FoE Kappa | Best FoE Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HaSCoSVA | 0.7310 | 0.7788 (+0.0478) | 0.5591 | 0.7720 (+0.0410) | 0.5465 | 0.5902 | **0.8166** (+0.0856) | **0.6331** | 0.9116 |
| HatEval | 0.7300 | 0.6597 (-0.0703) | 0.3373 | 0.6474 (-0.0826) | 0.2977 | 0.3725 | **0.8048** (+0.0748) | **0.6111** | 0.8074 |
| HaterNet | 0.6110 | 0.6834 (+0.0724) | 0.3879 | 0.7085 (+0.0975) | 0.4240 | 0.3161 | **0.8417** (+0.2307) | **0.6837** | 0.8825 |
| MTLHate | N/A | 0.7076 (N/A) | 0.4156 | 0.7051 (N/A) | 0.4106 | 0.3860 | **0.8273** (N/A) | **0.6547** | **0.8282** |

In the direct comparison, FoE dominates F1-macro on all four datasets and also Kappa in all four cases. In the datasets where accuracy is reported, FoE also achieves the best values. Majority vote provides a stable reference, but it does not surpass FoE on any primary metric; its only partial advantage is Fleiss Kappa, which measures agreement among multiple voters rather than classification quality.

For this reason, the evidence in this experimentation supports FoE as an appropriate strategy for assisted annotation of hate speech corpora: it yields better aggregated decisions than a single expert or majority voting, and it does so robustly even under strong class imbalance or greater domain heterogeneity.
