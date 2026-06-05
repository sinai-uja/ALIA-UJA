# Annotation Data Process - ALIA Spanish Discriminative Hate Speech Corpus Documentation

This document closes the end-to-end process of building the annotated corpus. The goal of this final stage is simple: take the curated Spanish corpus, annotate it with several LLM experts and fuse those annotations into a single prediction thanks to the best fusion model obtained as a reusable artifact for later analysis.

## 1. Best FoE model search and conducted runs

Based on the FoE experiments described in [foe_experiments.md](foe_experiments.md), the search for the best fusion model was carried out on the four reference datasets used throughout the project: HaSCoSVA, HaterNet, HatEval, and MTLHate. For this final stage, the dataset splits were pooled across corpora in the way described in the FoE methodology: all train splits were combined to fit the candidate fusion models, all validation splits were combined to compare and rank candidates, and all test splits were held back for the final one-time evaluation of the selected artifact.

The actual search was performed as a cross-evaluation over a controlled configuration space of FoE candidates. Each candidate combined the three kinds of inputs: the binary annotations produced by the LLM experts, the embeddings of the comments, and the embeddings of the generated explanations. The ranking criterion was the **pooled validation** `f1_macro`, with `kappa` used as a secondary tie-breaker in the ranking tables.

In summary, the conducted runs in this stage followed this sequence:

1. Pool the train/validation/test splits of the four reference datasets.
2. Train multiple FoE candidates on the pooled train data.
3. Rank candidates by pooled validation `f1_macro`.
4. Select the best candidate configuration.
5. Retrain that configuration as the final persisted model.
6. Evaluate the persisted model once on the pooled test splits and report those metrics as final.

This distinction between the ranked candidate and the retrained persisted model is important for interpreting the numbers in this document: the ranking files tell us which configuration was selected, while the persisted run log tells us the final validation and test performance of the model that was actually kept.

## 2. Best-ranked configuration and results

The top-ranked candidate combines three few-shot prompted experts (`apertus_it_8B`, `gemma_4_31B_it`, and `minimax_m2.5`), `sentence_transformer` embeddings, and the `sentiment_mlp` fusion head. That candidate was selected because it obtained the best pooled validation `f1_macro` in the ranking table, with `kappa` used as a secondary tie-breaker. Its configuration can be summarized as follows:

| Parameter | Value |
|---|---|
| `enhanced_max_features` | `2000` |
| `enhanced_method` | `sentence_transformer` |
| `enhanced_pca_components` | `128` |
| `fusion_architecture.kind` | `sentiment_mlp` |
| `fusion_architecture.hidden_dim` | `1024` |
| `fusion_architecture.dropout` | `0.5` |
| `input_features.binary_annotations` | `true` |
| `input_features.comment_embeddings` | `true` |
| `input_features.explanation_embeddings` | `true` |
| `model_prompt_pairs` | `apertus_it_8B + gemma_4_31B_it + minimax_m2.5` |
| `learning_rate` | `0.001` |
| `batch_size` | `64` |
| `epochs` | `100` |
| `selection_metric` | `f1_macro` |
| `random_state` | `42` |

The metrics that made this configuration the best-ranked candidate were: `f1_macro = 0.8180`, `kappa = 0.6360`, `accuracy = 0.8241`, with `n_test = 7122`.


## 3. Final model and its performance

After the best-ranked configuration was selected, the model was retrained from scratch on the pooled training data and persisted as `fusion_model.pkl`.

The final aggregated validation and test metrics for the persisted model are:

| Split | Accuracy | F1-macro | Kappa |
|---|---:|---:|---:|
| Pooled Validation | 0.8230 | 0.8194 | 0.6389 |
| Pooled Test | 0.8179 | 0.8112 | 0.6225 |

## 4. Annotation process and stats

The curated corpus was annotated automatically by the set of few-shot prompted LLM experts used in this project. Annotations were produced as per-model JSONL files (one record per comment and model) using the pipeline described in [foe_experiments.md](foe_experiments.md).

Below are the verified summary statistics computed on the intersection of the three models `apertus_it_8B`, `gemma_4_31B_it` and `minimax_m2.5`:

| Metric | Value |
|---|---:|
| Number of comments (common IDs) | 228,708 |
| Fleiss' Kappa (3 models) | 0.49827 |
| Global majority-vote hate (%) | 25.97% |
| Global majority-vote no-hate (%) | 74.03% |


Per-model label distribution (on the common IDs):

| Model | Hate (count) | Hate (%) | No-hate (count) | No-hate (%) |
|---|---:|---:|---:|---:|
| apertus_it_8B | 60,323 | 26.38% | 168,385 | 73.62% |
| gemma_4_31B_it | 47,463 | 20.75% | 181,245 | 79.25% |
| minimax_m2.5 | 74,110 | 32.40% | 154,598 | 67.60% |

Majority-vote distribution by source (on the common IDs):

| Source | Total (count) | Hate (count) | Hate (%) | No-hate (count) | No-hate (%) |
|---|---:|---:|---:|---:|---:|
| youtube | 201,612 | 56,812 | 28.18% | 144,800 | 71.82% |
| tiktok | 27,096 | 2,581 | 9.53% | 24,515 | 90.47% |

## 5. FoE classification

The following aggregates are computed over the final corpus in [SINAI/ALIA-es-discriminative-hate-speech](https://huggingface.co/datasets/SINAI/ALIA-es-discriminative-hate-speech).

| Metric | Value |
|---|---:|
| Number of records | 228,708 |
| `foe_class = 0` (no-hate) | 167,774 (73.36%) |
| `foe_class = 1` (hate) | 60,934 (26.64%) |

The distribution of `foe_score` (continuous confidence in the hate prediction) is available as a histogram image: [foe_score_hist.png](foe_score_hist.png).

## 6. Human Validation and Agreement (Prolific)

To validate the quality of the automated annotation pipeline and the Fusion of Experts (FoE) classifier, a validation study was conducted with human annotators through the **[Prolific](https://www.prolific.com/)** platform. All metrics reported below (Fleiss' Kappa, Cohen's Kappa, F1-macro, and Accuracy) are defined in [foe_experiments.md](foe_experiments.md#5-evaluation-metrics) (Section 5).

### Methodology and Participant Selection
- **Annotators**: Two human annotators were selected from the Prolific participant pool based on strict demographic filters to ensure they were representative of the native Spanish context:
  - **Nationality**: Spain
  - **Country of Birth**: Spain
  - **Current Country of Residence**: Spain
  - **First Language**: Spanish
  - **Primary Language**: Spanish
  - **Fluent Languages**: Spanish
- **Sample Selection**: A sample of **3,000 comments** was selected using a source-balanced stratified diversity sampling methodology:
  - **Stratification**: The sample is equally divided across the content sources (YouTube and TikTok), targeting 1,500 comments per source. Within each source, the selection is further stratified to preserve the exact proportion of positive (hate) and negative (non-hate) predictions generated by the FoE model.
  - **Candidate Prefiltering**: For each stratum (source and label combination), comments are vectorized using TF-IDF (unigrams and bigrams, up to 50,000 features). To ensure memory efficiency, a candidate pool of the top 4,000 most representative comments (highest cosine similarity to the stratum's average TF-IDF vector/centroid) is pre-filtered.
  - **MMR Diversity Selection**: Within each candidate pool, Maximal Marginal Relevance (MMR) is applied with a diversity weight of $\lambda = 0.7$. This iteratively selects comments that are highly representative of the stratum's semantic core while minimizing similarity to comments already selected, maximizing semantic diversity in the final sample.
- **Anonymization**: Human annotators' Prolific identifiers have been anonymized in the reports as `Annotator 1` and `Annotator 2`.

### Human Annotation Statistics
- **Annotated samples**: 3,000 comments per annotator (total of 6,000 annotations).
- **Included users**: 2 annotators.

#### Annotations per User

| Annotator | Total Annotations | Non-hate | Hate | % Non-hate | % Hate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Annotator 1 | 3,000 | 2,715 | 285 | 90.500% | 9.500% |
| Annotator 2 | 3,000 | 2,538 | 462 | 84.600% | 15.400% |
| **Total** | **6,000** | **5,253** | **747** | **87.550%** | **12.450%** |

### Agreement between Annotators and FoE Model
- **Fleiss' Kappa (Annotators + FoE)**: **0.474** (indicating moderate agreement).

### Agreement between Human Annotators

| Annotator A | Annotator B | Common Samples | Accuracy | F1-macro | Cohen's Kappa |
| --- | --- | ---: | ---: | ---: | ---: |
| Annotator 1 | Annotator 2 | 3,000 | 0.892 | 0.753 | **0.510** |

### Agreement between Human Annotators vs FoE

| Annotator | Common Samples | Accuracy vs FoE | F1-macro vs FoE | Cohen's Kappa vs FoE |
| --- | ---: | ---: | ---: | ---: |
| Annotator 1 | 3,000 | 0.866 | 0.737 | **0.485** |
| Annotator 2 | 3,000 | 0.837 | 0.723 | **0.448** |

### Dataset Models vs Each Human Annotator

| Annotator | Model | Common Samples | Accuracy | F1-macro | Cohen's Kappa |
| --- | --- | ---: | ---: | ---: | ---: |
| Annotator 1 | `apertus_it_8B` | 3,000 | 0.833 | 0.649 | 0.308 |
| Annotator 1 | `gemma_4_31B_it` | 3,000 | 0.883 | 0.744 | **0.495** |
| Annotator 1 | `minimax_m2.5` | 3,000 | 0.798 | 0.667 | 0.369 |
| Annotator 1 | `majority_vote(apertus_it_8B, gemma_4_31B_it, minimax_m2.5)` | 3,000 | 0.873 | 0.737 | **0.482** |
| Annotator 2 | `apertus_it_8B` | 3,000 | 0.803 | 0.647 | 0.295 |
| Annotator 2 | `gemma_4_31B_it` | 3,000 | 0.903 | 0.820 | **0.640** |
| Annotator 2 | `minimax_m2.5` | 3,000 | 0.820 | 0.734 | **0.479** |
| Annotator 2 | `majority_vote(apertus_it_8B, gemma_4_31B_it, minimax_m2.5)` | 3,000 | 0.879 | 0.786 | **0.572** |

## **Example Record (random sample)**

Below is a randomly selected example from the final corpus (fields of interest shown):

```json
{
  "id": "record_199077",
  "source": "youtube",
  "text": "Moros fuera TVE sicópatas iros a marruecos",
  "foe_class": 1,
  "foe_score": 0.9392520189285278,
  "apertus_it_8B": {
    "class": 1,
    "explanation": "El comentario contiene lenguaje degradante hacia colectivos vulnerables (moros) y utiliza un término despectivo (sicópatas) que deshumaniza a las personas de origen marroquí. Además, incita a la discriminación y exclusión al pedir que se vayan a Marruecos."
  },
  "gemma_4_31B_it": {
    "class": 1,
    "explanation": "El comentario constituye discurso de odio ya que utiliza el término 'moros' de forma despectiva y exige la expulsión de un grupo basado en su origen nacional o etnia ('fuera', 'iros a marruecos'). Esto cumple con los criterios de llamar explícitamente a la exclusión y segregación de un grupo protegido, promoviendo la xenofobia."
  },
  "minimax_m2.5": {
    "class": 1,
    "explanation": "El comentario 'Moros fuera TVE sicópatas iros a marruecos' contiene discurso de odio porque utiliza el término despectivo 'moros' para referirse a personas de origen árabe o norteafricano, lo cual es un insulto étnico. La expresión 'fuera' implica una llamada a la expulsión o exclusión de este colectivo, lo cual constituye incitación a la discriminación y segregación. Además, el insulto 'sicópatas' directed toward TVE (la televisión pública española) y la orden 'iros a marruecos' refuerzan el mensaje de rechazo hacia personas de origen marroquí o magrebí. El comentario combina un insulto étnico con una llamada explícita a la exclusión, cumpliendo los criterios de discurso de odio."
  }
}
```

The example above illustrates how the per-expert annotations, the fused `foe_score` and the final `foe_class` are stored together for each comment in the released corpus.

