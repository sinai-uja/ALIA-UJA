# Curated Datasets — Filtering, Deduplication, and Anonymization

This directory contains the documentation by steps for the **curation** process (filtering, deduplication, and anonymization) derived from the raw data collected from YouTube and TikTok. The pipeline is based on [datatrove](https://github.com/huggingface/datatrove), the toolchain used by Hugging Face to prepare [HuggingFaceFW/fineweb](https://huggingface.co/datasets/HuggingFaceFW/fineweb).


## Filtering and Deduplication Process

### Stage 1: Filtering and anonymization
**Input:** Raw JSONL without processing (YouTube with `cid`, TikTok with `id`)

#### Filtering steps (in order):

1. **LambdaFilter: Emoji-only check**
   - Discards comments that contain only emojis and whitespace
   - Removes reaction noise without textual content
   - Typically removes ~5–10% of comments

2. **LanguageFilter: Spanish detection (fastText)**
   - Detects language using fastText (LID model)
   - Requires a score >= `language_threshold` (default: 0.7)
   - Removes comments in other languages (English, other European languages, Arabic, etc.)
   - Typically removes ~20–30% of comments

3. **LambdaFilter: Spam heuristic**
   - Discards comments with:
     - Too many URLs (> `max_urls`, default: 1)
     - Too many mentions (> `max_mentions`, default: 5)
     - Repeated character sequences (> `max_repeated_seq`, default: 15 identical characters)
     - High non-alphabetic character ratio (> `max_nonalpha_ratio`, default: 0.7)
   - Removes bot and advertising spam
   - Typically removes ~1–5% of comments

4. **LambdaFilter: Anonymization**
   - Replaces all `@...` mentions with the generic `@usuario`
   - Preserves privacy without removing the fact that someone is being mentioned
   - Applied to **all comments that pass the previous filters**

### Intermediate State (after Stage 1)
After Stage 1 filtering the dataset is reduced and anonymized:
- **Removed:** Comments with no text, emoji-only content, non-Spanish content, heuristic spam
- **Anonymized:** All `@...` mentions replaced with the generic `@usuario`
- **Only fields kept:** `id` and `text` (metadata discarded)
- **Actual size after Stage 1:**
  - TikTok/by_hashtag: 27,387 comments
  - YouTube/Hortaleza: 8,507 comments
  - YouTube/Jumilla: 19,502 comments
  - YouTube/Torre Pacheco: 177,197 comments
  - **Total intermediate:** 232,593

### Stages 2–4: MinHash Deduplication
**Input:** Intermediate JSONL with deduplication candidates

MinHash is a similar-document deduplication algorithm used by FineWeb. It consists of 3 sub-stages:

#### Stage 2: Signature computation
- Computes a MinHash signature for each document
- Algorithm: character n-grams (5-grams), hashing
- Cost: O(n) per document

#### Stage 3: Bucketing + Clustering
- Groups documents into buckets based on the signature
- Identifies similarity clusters (near-duplicates)
- Detects transitive duplicates
- **Restriction:** This stage can ONLY run with `world_size=1` (no parallelism, sequential)

#### Stage 4: Filter and keep
- Removes duplicates while keeping 1 copy per cluster
- Reads original comments and iterates through clusters
- Writes only documents that do not appear in `removed_duplicates/`

### Final State (after Stages 2–4)
After MinHash deduplication the dataset is deduplicated and written out:
- **Deduplicated:** Exact duplicates and similar near-duplicates removed (MinHash clustering)
- **Only fields kept:** `id` and `text` (uncompressed, flat JSONL format)
- **Actual final size:**
  - TikTok/by_hashtag: 27,096 comments
  - YouTube/Hortaleza: 8,426 comments
  - YouTube/Jumilla: 19,207 comments
  - YouTube/Torre Pacheco: 173,979 comments
  - **Total final:** 228,708
- **Combined:** A single `curated.jsonl` file at the root with `id`, `source`, and `text` fields

## Process Summary

| Dataset | Raw | Intermediate | Final | Removed in Stage 1 | Removed in Stage 2-4 |
|---------|-----:|-------------:|------:|-------------------:|---------------------:|
| TikTok/by_hashtag | 42,818 | 27,387 | 27,096 | 15,431 | 291 |
| YouTube/Hortaleza | 10,731 | 8,507 | 8,426 | 2,224 | 81 |
| YouTube/Jumilla | 24,195 | 19,502 | 19,207 | 4,693 | 295 |
| YouTube/Torre Pacheco | 223,811 | 177,197 | 173,979 | 46,614 | 3,218 |
| **TOTAL** | **301,555** | **232,593** | **228,708** | **68,962** | **3,885** |



