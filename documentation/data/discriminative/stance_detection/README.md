# Stance Detection Corpus — Data Documentation

This document explains the origin of the data, the filtering rationale, raw-data statistics, and the terms of service under which the source data is published.

---

## Table of Contents

- [Source Platform](#source-platform)
- [Raw Data Statistics](#raw-data-statistics)
- [Why Comment Votes Are Discarded](#why-comment-votes-are-discarded)
- [Why "Debate" vs "Proposal" Is Not Used](#why-debate-vs-proposal-is-not-used)
- [Filtering Pipeline](#filtering-pipeline)
  - [Step 0 — First-level comments only](#step-0--first-level-comments-only)
  - [Step 1 — Unify debates and proposals into targets](#step-1--unify-debates-and-proposals-into-targets)
  - [Step 2 — Vote counting](#step-2--vote-counting)
  - [Step 3 — Join comments with targets](#step-3--join-comments-with-targets)
  - [Step 4 — Attach vote counts](#step-4--attach-vote-counts)
  - [Step 5 — Clean and export](#step-5--clean-and-export)
  - [Step 6 — Select annotation columns](#step-6--select-annotation-columns)
- [Filter Summary](#filter-summary)
- [Sampling for Annotation](#sampling-for-annotation)
- [Annotation Guide](#annotation-guide)
- [Terms of Service](#terms-of-service)

---

## Source Platform

**Decide Madrid** is the participatory democracy portal of the *Ayuntamiento de Madrid* (Madrid City Council). Citizens can open debates and proposals on local policy issues, and other citizens respond with comments.

- **Platform:** [decide.madrid.es](https://decide.madrid.es)
- **Open Data Portal:** [datos.madrid.es](https://datos.madrid.es)
- **Publisher:** Ayuntamiento de Madrid
- **License:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)

---

## Raw Data Statistics

The following table summarizes the raw CSV files downloaded from the Decide Madrid Open Data Portal.

| File | Rows | Description |
|------|------|-------------|
| `comments.csv` | 131,418 | All comments posted on debates, proposals, polls and topics |
| `debates.csv` | 5,101 | Debate topics (title, description, votes) |
| `proposals.csv` | 33,879 | Citizen proposals (title, description, votes) |
| `votes.csv` | 4,132,933 | Individual votes on topics and comments |

**Comment characteristics (raw):**

| Metric | Value |
|--------|-------|
| Total comments | 131,418 |
| First-level comments | 85,297 |
| Replies (comments with non-empty `ancestry`) | 46,121 (35.1%) |
| Comments on Proposals | 92,575 |
| Comments on Debates | 33,121 |
| Comments on Polls | 5,600 |
| Comments on Topics | 122 |
| Average comment length | 274.4 characters |
| Median comment length | 192.0 characters |
| Minimum comment length | 1 character |
| Maximum comment length | 11,128 characters |

---

## Why Comment Votes Are Discarded

The original files contain vote counts (supports and rejections) for both topics and individual comments. In an exploratory phase, these votes were extracted as potential *silver labels* or weak supervision for stance detection. However, **comment votes are not a reliable proxy for the comment's stance toward the topic**:

- A comment that is **against** a popular proposal may receive many support votes from users who share that criticism. The support vote means *"I agree with this comment"*, not *"this comment supports the topic"*.
- A comment that is **in favor** of an unpopular proposal may receive massive rejections, not because it is poorly argued, but because the majority opposes the topic.

In other words, votes measure the **social approval of the comment among users**, not the **comment's stance toward the topic**. Confusing both signals would introduce systematic noise into the labels. For this reason, the final corpus does not include votes, and stance annotation was performed entirely by human annotators.

---

## Why "Debate" vs "Proposal" Is Not Used

The Decide Madrid platform offers two types of topics: *Debates* (open discussions) and *Proposals* (citizen petitions that can be signed). However, this distinction **is not reliable** in practice: users freely chose the type and frequently classified concrete proposals as "Debate" and vice versa.

**Example — A "Debate" that is actually a proposal:**

> `id=5 | "ARREGLAR LOS REBAJES DE LOS BORDILLOS PARA FACILITAR EL PASO DE SILLAS DE RUEDAS" | Type: Debate`  
> Description: *"[...] PROPONGO mejorar el estado de las aceras y especialmente de los bordillos en las zonas de cruce [...]"*

The use of "PROPONGO" ("I propose") in all caps inside a "Debate" shows that the user did not distinguish between the two types.

This pattern is systemic. Introducing `Target Type` as a feature in a stance detection model would add noisy signal. For human annotation, forcing annotators to distinguish between "Debate" and "Proposal" when the topic author did not classify it correctly increases confusion without adding useful information.

**Practical consequence:** debates and proposals are treated uniformly as *targets*. The annotation guide uses a single definition: FAVOR = the comment supports addressing the problem OR implementing the initiative, regardless of how the author classified it on the platform.

---

## Filtering Pipeline

The script `build_corpus.py` processes the raw CSVs through the following steps.

### Step 0 — First-level comments only

Before any join, `comments.csv` is filtered to keep **only comments that respond directly to a debate or proposal** (first-level comments). Comments that reply to other comments are discarded.

The `ancestry` column in `comments.csv` indicates hierarchy:
- Empty `ancestry` → first-level comment, responds to the topic ✓
- `ancestry = "14"` → replies to comment #14 ✗
- `ancestry = "48/52"` → replies to comment #52 (which is a reply of #48) ✗

**Impact:** out of 131,418 total comments in `comments.csv`, **46,121 replies (35.1%)** are removed and **85,297 first-level comments** are kept.

**Why this filter is necessary for stance detection:** replies express stance toward another commenter, not toward the topic. Without this filter, the model would have to interpret sentences like *"Honestly, these duplications worsen the problem"* without knowing who is being addressed, making it impossible to determine stance toward the topic.

### Step 1 — Unify debates and proposals into targets

`debates.csv` and `proposals.csv` are combined into a single target table. Title and description are kept. The script also extracts votes and target type (`Debate`/`Proposal`) at this stage for reference in the intermediate corpus.

Descriptions are cleaned of HTML (tags like `<p>`, `<br>`, line breaks, etc.) so the corpus contains plain text.

### Step 2 — Vote counting

From `votes.csv`, only votes on comments are kept (`votable_type = 'Comment'`). The data is grouped by comment ID to count how many `true` (supports) and `false` (rejections) each comment accumulated.

### Step 3 — Join comments with targets

Each row of `comments.csv` is linked to its topic (debate or proposal) using `commentable_id` + `commentable_type` as the join key.

### Step 4 — Attach vote counts

The vote count from Step 2 is attached to each comment using the comment `id`.

### Step 5 — Clean and export

Comments without an identifiable topic (orphan comments) and comments whose targets lack a description are dropped, and the result is exported as `corpus_stance_madrid_recuento.csv`.

### Step 6 — Select annotation columns

The intermediate corpus contains 8 columns, including votes and target type. At the sampling stage (`sampling.py`), these columns are dropped and the final annotation corpus retains **only 4 fields**: `id`, `target`, `description`, `comment`.

The reasons for dropping these columns are explained above:
- **Comment votes:** not a stance proxy — they measure social approval, not stance toward the topic.
- **Target type** (`Debate`/`Proposal`): the distinction is unreliable because platform users did not respect it.
- **Target votes:** not relevant for determining the stance of an individual comment.

These columns are kept in the intermediate corpus as reference for possible future analysis, but they are not part of the annotation task or the published corpus.

---

## Filter Summary

| Filter | Removed | Reason |
|--------|---------|--------|
| Replies (non-empty `ancestry`) | 46,121 (35.1%) | They respond to another user, not the topic. Stance is not interpretable without thread context. |
| Proposals with truncated title (≥80 chars) | 1,079 proposals | Incomplete title: useless as a target in NLI. |
| Comments that are basically just URLs (<30 chars of real text) | 4,599 (5.8%) | Spam linking to other proposals, with no actual opinion. |
| Automatic welcome messages | 1,456 (1.9%) | Bot welcoming new users with a link to the non-repeated proposals list, with no opinion on the topic. |
| Pattern "Listado de Propuestas NO Repetidas" | 709 (1.0%) | Automatic or copy-paste messages notifying that the proposal was added to an external index. They express no stance on the topic. |
| Topics "#TúPreguntas" | 1,150 (1.6%) | Q&A sessions with city council members. Comments are questions to a politician, not stances on a citizen initiative. |
| Targets without description | 9,509 (13.4%) | Proposals with no descriptive text: the title alone is not enough context for NLI. |
| Orphan comments (no associated topic) | residual | Join mismatch after filtering proposals. |
| **Final corpus** | **61,716** | First-level comments, with substantial text, complete title, and target description. |

---

## Sampling for Annotation

### Why 3,000 comments and not the full corpus?

The filtered corpus contains **~61,716 comments** across **1,140 topics**. Annotating the full corpus with 3 annotators per comment (the minimum to compute Fleiss' kappa) would require more than 180,000 individual annotation tasks, implying a high cost on Prolific and several months of work. Within our budget, we opted for a representative sample of **3,000 comments** (~4.9% of the corpus).

### How they are selected: stratified sampling by topic

The sample is **not random**: the 3,000 comments are selected through **proportional stratified sampling by topic**, ensuring that all relevant topics are represented and that topics with more activity contribute more samples.

#### Step 1 — Pre-sampling quality filters

Before sampling, additional filters are applied on the 61,716-comment corpus to ensure only high-quality texts enter the sample:

| Filter | Criterion |
|--------|-----------|
| Minimum length | ≥ 80 characters |
| Maximum length | ≤ 800 characters |
| Minimum words | ≥ 5 words |
| Target description with real content | After removing URLs, description must have ≥ 30 characters |
| Deduplication | Duplicate (topic, text) pairs are removed (same comment posted multiple times) |

After these filters, a **quality pool** of ~61,000 unique comments remains.

#### Step 2 — Filter out low-activity topics

Only topics with **≥ 10 quality comments** enter the sampling. Topics with fewer comments are discarded because proportional sampling cannot give them useful minimum representation.

#### Step 3 — Calculate slots per topic (proportional sampling)

For each eligible topic, the number of comments to include in the sample (*slots*) is calculated as:

```
slots = clamp(round(n_quality × 0.33), min=3, max=50)
```

Where:
- `n_quality` = comments from the topic that pass the quality filters
- **0.33** = sampling rate (~33% of the topic's quality comments)
- **minimum 3** = guarantee of representation for small topics
- **maximum 50** = cap so the most active topics do not dominate the sample

This produces a distribution **proportional to topic size**, not uniform: a topic with 150 quality comments contributes 50 samples; a topic with 9 contributes 3.

#### Step 4 — Length diversity within each topic

So that each topic is represented by texts of different lengths, selection within each topic is stratified by length into three bands:

| Band | Range |
|------|-------|
| Short | 80 – 200 characters |
| Medium | 200 – 450 characters |
| Long | 450 – 800 characters |

The algorithm first takes at least one comment from each available band, then fills the remaining slots with a random sample from the rest of the topic.

#### Step 5 — Adjustment to exactly 3,000

After proportional sampling, the total may be slightly above or below 3,000:

- **If excess:** comments are removed starting from the most represented topics (preserving the minimum of 3 per topic).
- **If deficit:** filled with reserve comments (comments that passed the filters but were not selected), prioritizing topics with the largest available pool.

#### Reproducibility

The entire process uses `RANDOM_SEED = 42`. Running `sampling.py` on the same `corpus_stance_madrid_recuento.csv` produces exactly the same sample.

### Sampling result

| Statistic | Value |
|-----------|-------|
| Comments in filtered corpus | ~61,716 |
| Pool after quality filters and deduplication | ~61,000 |
| Eligible topics (≥ 10 quality comments) | ~600+ |
| **Final sample** | **3,000 comments** |
| Length distribution | ~1,000 short / ~1,000 medium / ~1,000 long |

---

## Pilot Study

Before launching the full annotation campaign, a **pilot study** was conducted to validate the annotation guide, the Prolific setup, the Google Forms mechanics, and the time estimates.

### Pilot design

| Parameter | Value |
|-----------|-------|
| **Samples** | 100 comments |
| **Blocks** | 2 blocks of 50 real samples + 5 gold standards each |
| **Annotators** | 6 unique native Spanish speakers |
| **Annotations per sample** | 3 independent annotators |
| **Platform** | Prolific + Google Forms |

### What was validated

- **Annotation guide adequacy:** no annotator reported that the guide was unclear or unsuitable for the data. Optional observation fields were available but rarely used, indicating that the task was self-explanatory.
- **Gold standard pass rate:** all 6 annotators scored **100%** on the attention-check questions, confirming that the gold-standard design was effective and that the instructions were understood.
- **Timing:** the average completion time was approximately **40 minutes per 50 instances** (roughly 45–50 seconds per question, including reading the target description and the comment). This timing was used to set the reward and time limit for the full study on Prolific.
- **Form mechanics:** the Google Apps Script for automatic form generation worked correctly, the shuffle logic mixed gold standards among real samples without positional bias, and the Prolific completion redirect operated as expected.

### Impact on the full study

The pilot validated that:
1. The **annotation guide** was sufficient for native Spanish speakers without prior NLP training.
2. **3 annotators per sample** was the right balance between cost and agreement reliability.
3. A **block size of 55 questions** (50 real + 5 gold) was feasible within Prolific's recommended session length and Google Forms' usability limits.
4. The **stratification by comment length** (short/medium/long) inside each topic produced a balanced and representative block experience.

These parameters were carried over unchanged into the full study of 3,000 samples across 60 blocks.

---

## Annotation Guide

A detailed annotation guide was designed to support the Prolific annotators. It defines the three labels (**FAVOR**, **CONTRA**, **NEUTRAL**), provides a decision tree for difficult cases, and includes real-world examples drawn from the Decide Madrid platform.

The full guide (in Spanish) is available here: [guia_anotacion.md](guia_anotacion.md).

---

## Terms of Service

The original data is published by the **Ayuntamiento de Madrid** through its Open Data Portal under **CC BY 4.0**.

### What CC BY 4.0 allows

- **Commercial use** is permitted.
- **Modification and adaptation** are permitted.
- **Sharing and redistribution** are permitted.
- **Attribution is required.**

### Attribution requirement

When using this corpus or the raw data, you must credit the source:

> Original data: Ayuntamiento de Madrid, Decide Madrid platform, published under CC BY 4.0.

### What we do with the data

We download the raw CSVs from the Open Data Portal, apply the filtering and sampling pipeline described above, and publish the resulting annotated corpus under the same **CC BY 4.0** license. No personal data beyond what citizens voluntarily posted on a public platform is included. Platform-specific user IDs and metadata have been removed; only textual content (target title, target description, comment text) is retained.

### User responsibility

Users of this corpus are advised to apply additional privacy controls depending on the specific use case, particularly for applications involving personal data processing or re-identification risk analysis.
