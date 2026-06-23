import argparse
import asyncio
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import yaml
from openai import AsyncOpenAI
from tqdm import tqdm


TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
TRUNCATED_MARKERS = ("[truncated]", "<|im_end|", "<|endoftext|")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def stable_hash(*parts: str) -> str:
    joined = "\u241f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def char_ngrams(text: str, n: int) -> Counter:
    compact = re.sub(r"\s+", " ", text.lower()).strip()
    if not compact:
        return Counter()
    if len(compact) < n:
        return Counter([compact])
    return Counter(compact[i : i + n] for i in range(len(compact) - n + 1))


def chrf_score(a: str, b: str, max_order: int = 6, beta: float = 2.0) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    precisions = []
    recalls = []
    for n in range(1, max_order + 1):
        a_grams = char_ngrams(a, n)
        b_grams = char_ngrams(b, n)
        overlap = sum((a_grams & b_grams).values())
        precisions.append(overlap / max(sum(a_grams.values()), 1))
        recalls.append(overlap / max(sum(b_grams.values()), 1))

    precision = mean(precisions)
    recall = mean(recalls)
    if precision == 0.0 and recall == 0.0:
        return 0.0
    beta2 = beta * beta
    return (1 + beta2) * precision * recall / ((beta2 * precision) + recall)


def token_ngrams(tokens: list[str], n: int) -> Counter:
    if len(tokens) < n:
        return Counter()
    return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def bleu_score(candidate: str, reference: str, max_order: int = 4) -> float:
    candidate_tokens = TOKEN_RE.findall(candidate.lower())
    reference_tokens = TOKEN_RE.findall(reference.lower())
    if not candidate_tokens and not reference_tokens:
        return 1.0
    if not candidate_tokens or not reference_tokens:
        return 0.0

    log_precisions = []
    for n in range(1, max_order + 1):
        candidate_grams = token_ngrams(candidate_tokens, n)
        reference_grams = token_ngrams(reference_tokens, n)
        overlap = sum((candidate_grams & reference_grams).values())
        total = sum(candidate_grams.values())
        # Add-one smoothing keeps short but partially overlapping answers from becoming exactly 0.
        log_precisions.append(math.log((overlap + 1) / (total + 1)))

    brevity_penalty = 1.0
    if len(candidate_tokens) < len(reference_tokens):
        brevity_penalty = math.exp(1 - (len(reference_tokens) / len(candidate_tokens)))

    return brevity_penalty * math.exp(sum(log_precisions) / max_order)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p25": None, "median": None, "mean": None, "p75": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "p25": percentile(values, 0.25),
        "median": median(values),
        "mean": mean(values),
        "p75": percentile(values, 0.75),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    invalid_json = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                invalid_json.append({"line": line_number, "error": str(exc)})
                continue
            item["_line"] = line_number
            rows.append(item)
    return rows, invalid_json


def fingerprint_tokens(text: str, size: int = 80) -> str:
    tokens = TOKEN_RE.findall(text.lower())
    return " ".join(tokens[:size])


def find_near_duplicate_pairs(rows: list[dict[str, Any]], threshold: float, max_bucket_size: int) -> list[dict[str, Any]]:
    from difflib import SequenceMatcher

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        prompt = normalize_text(row.get("prompt")).lower()
        chosen = normalize_text(row.get("chosen")).lower()
        key = f"{token_count(prompt) // 25}:{token_count(chosen) // 25}"
        buckets[key].append(row)

    matches = []
    for bucket in buckets.values():
        if len(bucket) > max_bucket_size:
            continue
        for i, left in enumerate(bucket):
            left_text = normalize_text(left.get("prompt")) + "\n" + normalize_text(left.get("chosen"))
            for right in bucket[i + 1 :]:
                right_text = normalize_text(right.get("prompt")) + "\n" + normalize_text(right.get("chosen"))
                similarity = SequenceMatcher(None, left_text, right_text).ratio()
                if similarity >= threshold:
                    matches.append({"line_a": left["_line"], "line_b": right["_line"], "similarity": similarity})
    return matches


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def load_embedding_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


async def create_embedding_batch(
    client: AsyncOpenAI,
    model: str,
    texts: list[str],
    start_index: int,
) -> tuple[int, list[list[float] | None]]:
    response = await client.embeddings.create(model=model, input=texts)
    embeddings = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    return start_index, embeddings


async def create_embedding_batch_with_retry(
    client: AsyncOpenAI,
    model: str,
    texts: list[str],
    start_index: int,
    retries: int,
    retry_base_seconds: float,
    min_batch_size: int,
    request_timeout: float,
    skip_failed_embeddings: bool,
) -> tuple[int, list[list[float] | None]]:
    last_error = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(
                create_embedding_batch(client, model, texts, start_index),
                timeout=request_timeout,
            )
        except Exception as exc:
            last_error = exc
            print(
                f"Embedding batch failed: start={start_index}, size={len(texts)}, "
                f"attempt={attempt + 1}/{retries + 1}, error={type(exc).__name__}"
            )
            if attempt < retries:
                await asyncio.sleep(retry_base_seconds * (2**attempt))

    if len(texts) > min_batch_size:
        midpoint = len(texts) // 2
        left_start, left_embeddings = await create_embedding_batch_with_retry(
            client,
            model,
            texts[:midpoint],
            start_index,
            retries,
            retry_base_seconds,
            min_batch_size,
            request_timeout,
            skip_failed_embeddings,
        )
        right_start, right_embeddings = await create_embedding_batch_with_retry(
            client,
            model,
            texts[midpoint:],
            start_index + midpoint,
            retries,
            retry_base_seconds,
            min_batch_size,
            request_timeout,
            skip_failed_embeddings,
        )
        return left_start, left_embeddings + right_embeddings

    if skip_failed_embeddings:
        print(
            f"Skipping failed embedding text(s): start_index={start_index}, "
            f"batch_size={len(texts)}, error={type(last_error).__name__}"
        )
        return start_index, [None] * len(texts)

    raise RuntimeError(
        f"Embedding batch failed after {retries + 1} attempt(s); "
        f"start_index={start_index}, batch_size={len(texts)}"
    ) from last_error


async def compute_openai_embedding_similarities_async(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[float | None]:
    openai_config = config.get("openai", {})
    embedding_config = config.get("embeddings", {})
    model = embedding_config.get("model") or openai_config.get("model")
    if not model:
        raise ValueError("Falta embeddings.model en el YAML de embeddings.")

    client = AsyncOpenAI(
        api_key=openai_config.get("api_key", ""),
        base_url=openai_config.get("base_url"),
        timeout=embedding_config.get("timeout", 120),
        max_retries=embedding_config.get("max_retries", 2),
    )
    batch_size = int(embedding_config.get("batch_size", 64))
    max_concurrency = max(1, int(embedding_config.get("max_concurrency", 4)))
    request_retries = int(embedding_config.get("request_retries", 4))
    retry_base_seconds = float(embedding_config.get("retry_base_seconds", 2.0))
    min_batch_size = int(embedding_config.get("min_batch_size", 1))
    request_timeout = float(embedding_config.get("request_timeout", embedding_config.get("timeout", 120)))
    skip_failed_embeddings = bool(embedding_config.get("skip_failed_embeddings", True))

    texts = []
    for row in rows:
        texts.append(normalize_text(row.get("chosen")))
        texts.append(normalize_text(row.get("rejected")))

    batches = [(start, texts[start : start + batch_size]) for start in range(0, len(texts), batch_size)]
    queue: asyncio.Queue[tuple[int, list[str]] | None] = asyncio.Queue()
    for batch in batches:
        queue.put_nowait(batch)
    for _ in range(max_concurrency):
        queue.put_nowait(None)

    try:
        print(f"Embedding {len(texts)} responses in {len(batches)} batch(es), concurrency={max_concurrency}...")
        ordered_embeddings: list[list[float] | None] = [None] * len(texts)
        completed_embedding_slots = [False] * len(texts)
        progress = tqdm(total=len(batches), desc="Embedding batches", leave=False)

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    start, batch_texts = item
                    _, embeddings = await create_embedding_batch_with_retry(
                        client,
                        model,
                        batch_texts,
                        start,
                        request_retries,
                        retry_base_seconds,
                        min_batch_size,
                        request_timeout,
                        skip_failed_embeddings,
                    )
                    ordered_embeddings[start : start + len(embeddings)] = embeddings
                    completed_embedding_slots[start : start + len(embeddings)] = [True] * len(embeddings)
                    progress.update(1)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max_concurrency)]
        try:
            await asyncio.gather(*workers)
        finally:
            progress.close()

        if not all(completed_embedding_slots):
            missing = sum(1 for completed in completed_embedding_slots if not completed)
            raise RuntimeError(f"Missing {missing} embedding(s) after all requests completed.")

        similarities = []
        for i in range(0, len(ordered_embeddings), 2):
            chosen_embedding = ordered_embeddings[i]
            rejected_embedding = ordered_embeddings[i + 1]
            if chosen_embedding is None or rejected_embedding is None:
                similarities.append(None)
            else:
                similarities.append(cosine_similarity(chosen_embedding, rejected_embedding))
        return similarities
    finally:
        for task in locals().get("workers", []):
            if not task.done():
                task.cancel()
        if "workers" in locals():
            await asyncio.gather(*workers, return_exceptions=True)
        await client.close()


def compute_openai_embedding_similarities(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[float | None]:
    return asyncio.run(compute_openai_embedding_similarities_async(rows, config))


def audit_file(path: Path, args: argparse.Namespace, embedding_config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rows, invalid_json = load_jsonl(path)
    missing_or_empty = []
    suspicious_truncation = []
    exact_prompt_chosen = defaultdict(list)
    exact_prompt = defaultdict(list)
    prompt_chosen_fingerprint = defaultdict(list)
    chosen_lengths = []
    rejected_lengths = []
    length_ratios = []
    chrf_scores = []
    bleu_scores = []
    clean_rows = []
    metric_rows = []

    for row in tqdm(rows, desc=f"Auditing {path.name}", leave=False):
        prompt = normalize_text(row.get("prompt"))
        chosen = normalize_text(row.get("chosen"))
        rejected = normalize_text(row.get("rejected"))

        missing_fields = [field for field in ("prompt", "chosen", "rejected") if field not in row]
        empty_fields = [field for field, value in (("prompt", prompt), ("chosen", chosen), ("rejected", rejected)) if not value]
        if missing_fields or empty_fields:
            missing_or_empty.append({"line": row["_line"], "missing": missing_fields, "empty": empty_fields})
            continue

        if chosen.endswith(TRUNCATED_MARKERS) or rejected.endswith(TRUNCATED_MARKERS):
            suspicious_truncation.append({"line": row["_line"], "chosen_end": chosen[-40:], "rejected_end": rejected[-40:]})

        chosen_len = token_count(chosen)
        rejected_len = token_count(rejected)
        chosen_lengths.append(chosen_len)
        rejected_lengths.append(rejected_len)
        length_ratio = chosen_len / max(rejected_len, 1)
        chrf = chrf_score(chosen, rejected)
        bleu = bleu_score(chosen, rejected)
        length_ratios.append(length_ratio)
        chrf_scores.append(chrf)
        bleu_scores.append(bleu)

        exact_prompt_chosen[stable_hash(prompt, chosen)].append(row["_line"])
        exact_prompt[stable_hash(prompt)].append(row["_line"])
        prompt_chosen_fingerprint[stable_hash(fingerprint_tokens(prompt), fingerprint_tokens(chosen))].append(row["_line"])
        clean_rows.append(row)
        metric_rows.append(
            {
                "file": str(path),
                "line": row["_line"],
                "prompt_id": row.get("prompt_id", ""),
                "chosen_tokens": chosen_len,
                "rejected_tokens": rejected_len,
                "chosen_rejected_ratio": length_ratio,
                "chrf": chrf,
                "bleu": bleu,
                "short_rejected": rejected_len < args.short_rejected_tokens,
                "high_chrf": chrf > args.high_chrf_threshold,
                "high_bleu": bleu > args.high_bleu_threshold,
                "duplicate_prompt_chosen": "",
                "duplicate_prompt": "",
                "duplicate_prompt_chosen_fingerprint": "",
                "embedding_cosine": "",
                "high_embedding": "",
                "embedding_failed": "",
            }
        )

    near_duplicates = []
    if args.near_duplicates:
        near_duplicates = find_near_duplicate_pairs(clean_rows, args.near_duplicate_threshold, args.max_near_duplicate_bucket)
    embedding_similarities = None
    if args.embeddings:
        embedding_similarities = compute_openai_embedding_similarities(clean_rows, embedding_config)
        for metric_row, similarity in zip(metric_rows, embedding_similarities):
            if similarity is None:
                metric_row["embedding_cosine"] = ""
                metric_row["high_embedding"] = False
                metric_row["embedding_failed"] = True
            else:
                metric_row["embedding_cosine"] = similarity
                metric_row["high_embedding"] = similarity > args.high_embedding_threshold
                metric_row["embedding_failed"] = False

    exact_prompt_chosen_dupes = [lines for lines in exact_prompt_chosen.values() if len(lines) > 1]
    exact_prompt_dupes = [lines for lines in exact_prompt.values() if len(lines) > 1]
    fingerprint_dupes = [lines for lines in prompt_chosen_fingerprint.values() if len(lines) > 1]
    exact_prompt_chosen_duplicate_lines = {line for lines in exact_prompt_chosen_dupes for line in lines}
    exact_prompt_duplicate_lines = {line for lines in exact_prompt_dupes for line in lines}
    fingerprint_duplicate_lines = {line for lines in fingerprint_dupes for line in lines}
    for metric_row in metric_rows:
        line = metric_row["line"]
        metric_row["duplicate_prompt_chosen"] = line in exact_prompt_chosen_duplicate_lines
        metric_row["duplicate_prompt"] = line in exact_prompt_duplicate_lines
        metric_row["duplicate_prompt_chosen_fingerprint"] = line in fingerprint_duplicate_lines

    high_chrf_lines = [
        {"line": row["_line"], "chrf": score}
        for row, score in zip(clean_rows, chrf_scores)
        if score > args.high_chrf_threshold
    ]
    high_bleu_lines = [
        {"line": row["_line"], "bleu": score}
        for row, score in zip(clean_rows, bleu_scores)
        if score > args.high_bleu_threshold
    ]
    short_rejected_lines = [
        {"line": row["_line"], "rejected_tokens": rejected_len}
        for row, rejected_len in zip(clean_rows, rejected_lengths)
        if rejected_len < args.short_rejected_tokens
    ]

    duplicate_lines_to_remove = {line for lines in exact_prompt_chosen_dupes for line in lines[1:]}
    duplicate_lines_to_remove.update(line for lines in exact_prompt_dupes for line in lines[1:])
    filtered_rows = [{key: value for key, value in row.items() if key != "_line"} for row in clean_rows if row["_line"] not in duplicate_lines_to_remove]

    report = {
        "file": str(path),
        "total_lines": len(rows) + len(invalid_json),
        "valid_json_rows": len(rows),
        "usable_rows": len(clean_rows),
        "invalid_json_count": len(invalid_json),
        "missing_or_empty_count": len(missing_or_empty),
        "suspicious_truncation_count": len(suspicious_truncation),
        "invalid_json": invalid_json[: args.max_examples],
        "missing_or_empty": missing_or_empty[: args.max_examples],
        "suspicious_truncation": suspicious_truncation[: args.max_examples],
        "lengths": {
            "chosen_tokens": distribution(chosen_lengths),
            "rejected_tokens": distribution(rejected_lengths),
            "chosen_rejected_ratio": distribution(length_ratios),
        },
        "lexical_overlap": {
            "chrf": distribution(chrf_scores),
            f"pairs_above_{args.high_chrf_threshold}": len(high_chrf_lines),
            "chrf_examples": high_chrf_lines[: args.max_examples],
            "bleu": distribution(bleu_scores),
            f"bleu_pairs_above_{args.high_bleu_threshold}": len(high_bleu_lines),
            "bleu_examples": high_bleu_lines[: args.max_examples],
        },
        "duplicates": {
            "exact_prompt_chosen_groups": len(exact_prompt_chosen_dupes),
            "exact_prompt_chosen_extra_rows": sum(len(lines) - 1 for lines in exact_prompt_chosen_dupes),
            "exact_prompt_groups": len(exact_prompt_dupes),
            "exact_prompt_extra_rows": sum(len(lines) - 1 for lines in exact_prompt_dupes),
            "fingerprint_prompt_chosen_groups": len(fingerprint_dupes),
            "fingerprint_prompt_chosen_extra_rows": sum(len(lines) - 1 for lines in fingerprint_dupes),
            "near_prompt_chosen_pairs": len(near_duplicates),
            "near_prompt_chosen_examples": near_duplicates[: args.max_examples],
            "near_duplicates_enabled": args.near_duplicates,
        },
        "short_rejected": {
            f"under_{args.short_rejected_tokens}_tokens": len(short_rejected_lines),
            "examples": short_rejected_lines[: args.max_examples],
        },
        "embedding_similarity": None,
        "deduped_rows_if_written": len(filtered_rows),
    }

    if embedding_similarities is not None:
        valid_embedding_scores = [score for score in embedding_similarities if score is not None]
        failed_embedding = [
            {"line": row["_line"]}
            for row, score in zip(clean_rows, embedding_similarities)
            if score is None
        ]
        high_embedding = [
            {"line": row["_line"], "cosine": score}
            for row, score in zip(clean_rows, embedding_similarities)
            if score is not None and score > args.high_embedding_threshold
        ]
        report["embedding_similarity"] = {
            "cosine": distribution(valid_embedding_scores),
            f"pairs_above_{args.high_embedding_threshold}": len(high_embedding),
            "failed_pairs": len(failed_embedding),
            "failed_examples": failed_embedding[: args.max_examples],
            "examples": high_embedding[: args.max_examples],
        }

    return report, filtered_rows, metric_rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_metrics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "file",
        "line",
        "prompt_id",
        "chosen_tokens",
        "rejected_tokens",
        "chosen_rejected_ratio",
        "chrf",
        "bleu",
        "short_rejected",
        "high_chrf",
        "high_bleu",
        "duplicate_prompt_chosen",
        "duplicate_prompt",
        "duplicate_prompt_chosen_fingerprint",
        "embedding_cosine",
        "high_embedding",
        "embedding_failed",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def count_true(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def summarize_metric_rows(file_label: str, report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    chosen_tokens = [row["chosen_tokens"] for row in rows]
    rejected_tokens = [row["rejected_tokens"] for row in rows]
    ratios = [row["chosen_rejected_ratio"] for row in rows]
    chrf_scores = [row["chrf"] for row in rows]
    bleu_scores = [row["bleu"] for row in rows]
    embedding_scores = [
        row["embedding_cosine"]
        for row in rows
        if isinstance(row.get("embedding_cosine"), (int, float))
    ]

    chosen_dist = distribution(chosen_tokens)
    rejected_dist = distribution(rejected_tokens)
    ratio_dist = distribution(ratios)
    chrf_dist = distribution(chrf_scores)
    bleu_dist = distribution(bleu_scores)
    embedding_dist = distribution(embedding_scores)

    return {
        "file": file_label,
        "total_lines": report["total_lines"],
        "valid_json_rows": report["valid_json_rows"],
        "usable_rows": report["usable_rows"],
        "invalid_json_count": report["invalid_json_count"],
        "missing_or_empty_count": report["missing_or_empty_count"],
        "suspicious_truncation_count": report["suspicious_truncation_count"],
        "short_rejected_count": count_true(rows, "short_rejected"),
        "high_chrf_count": count_true(rows, "high_chrf"),
        "high_bleu_count": count_true(rows, "high_bleu"),
        "high_embedding_count": count_true(rows, "high_embedding"),
        "embedding_failed_count": count_true(rows, "embedding_failed"),
        "duplicate_prompt_chosen_rows": count_true(rows, "duplicate_prompt_chosen"),
        "duplicate_prompt_rows": count_true(rows, "duplicate_prompt"),
        "duplicate_prompt_chosen_fingerprint_rows": count_true(rows, "duplicate_prompt_chosen_fingerprint"),
        "exact_prompt_chosen_groups": report["duplicates"]["exact_prompt_chosen_groups"],
        "exact_prompt_groups": report["duplicates"]["exact_prompt_groups"],
        "fingerprint_prompt_chosen_groups": report["duplicates"]["fingerprint_prompt_chosen_groups"],
        "near_prompt_chosen_pairs": report["duplicates"]["near_prompt_chosen_pairs"],
        "deduped_rows_if_written": report["deduped_rows_if_written"],
        "chosen_tokens_mean": chosen_dist["mean"],
        "chosen_tokens_median": chosen_dist["median"],
        "chosen_tokens_p95": chosen_dist["p95"],
        "rejected_tokens_mean": rejected_dist["mean"],
        "rejected_tokens_median": rejected_dist["median"],
        "rejected_tokens_p95": rejected_dist["p95"],
        "length_ratio_mean": ratio_dist["mean"],
        "length_ratio_median": ratio_dist["median"],
        "length_ratio_p95": ratio_dist["p95"],
        "chrf_mean": chrf_dist["mean"],
        "chrf_median": chrf_dist["median"],
        "chrf_p95": chrf_dist["p95"],
        "bleu_mean": bleu_dist["mean"],
        "bleu_median": bleu_dist["median"],
        "bleu_p95": bleu_dist["p95"],
        "embedding_cosine_mean": embedding_dist["mean"],
        "embedding_cosine_median": embedding_dist["median"],
        "embedding_cosine_p95": embedding_dist["p95"],
    }


def write_summary_csv(path: Path, reports: list[dict[str, Any]], rows_by_file: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    all_rows = []
    all_report = {
        "total_lines": 0,
        "valid_json_rows": 0,
        "usable_rows": 0,
        "invalid_json_count": 0,
        "missing_or_empty_count": 0,
        "suspicious_truncation_count": 0,
        "duplicates": {
            "exact_prompt_chosen_groups": 0,
            "exact_prompt_groups": 0,
            "fingerprint_prompt_chosen_groups": 0,
            "near_prompt_chosen_pairs": 0,
        },
        "deduped_rows_if_written": 0,
    }

    for report in reports:
        file_rows = rows_by_file.get(report["file"], [])
        summary_rows.append(summarize_metric_rows(report["file"], report, file_rows))
        all_rows.extend(file_rows)
        for key in ("total_lines", "valid_json_rows", "usable_rows", "invalid_json_count", "missing_or_empty_count", "suspicious_truncation_count", "deduped_rows_if_written"):
            all_report[key] += report[key]
        for key in all_report["duplicates"]:
            all_report["duplicates"][key] += report["duplicates"][key]

    summary_rows.append(summarize_metric_rows("ALL", all_report, all_rows))

    fieldnames = list(summary_rows[0].keys()) if summary_rows else []
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit DPO JSONL files for format, duplicates, and preference-signal quality.")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("dpo_data")], help="JSONL file(s) or directories to audit.")
    parser.add_argument("--report", type=Path, default=Path("dpo_data/audit_report.json"), help="Path for the JSON audit report.")
    parser.add_argument("--metrics-csv", type=Path, default=Path("dpo_data/audit_metrics.csv"), help="Path for the summary metrics CSV.")
    parser.add_argument("--write-deduped", action="store_true", help="Write exact prompt/chosen and prompt-only deduplicated JSONL files.")
    parser.add_argument("--deduped-dir", type=Path, default=Path("dpo_data/deduped"), help="Output directory for deduplicated JSONL files.")
    parser.add_argument("--near-duplicates", action="store_true", help="Run the slower SequenceMatcher near-duplicate pass.")
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.94, help="SequenceMatcher threshold for near duplicate prompt+chosen pairs.")
    parser.add_argument("--max-near-duplicate-bucket", type=int, default=500, help="Skip near-duplicate comparison for oversized length buckets.")
    parser.add_argument("--short-rejected-tokens", type=int, default=20, help="Rejected responses shorter than this are flagged.")
    parser.add_argument("--high-chrf-threshold", type=float, default=0.85, help="chrF scores above this are flagged as low-contrast pairs.")
    parser.add_argument("--high-bleu-threshold", type=float, default=0.60, help="BLEU scores above this are flagged as low-contrast pairs.")
    parser.add_argument("--embeddings", action="store_true", help="Compute chosen/rejected embedding cosine similarity with an OpenAI-compatible embedding server.")
    parser.add_argument("--embedding-config", type=Path, default=Path("config_embeddings.yaml"), help="YAML config with OpenAI-compatible embedding server settings.")
    parser.add_argument("--high-embedding-threshold", type=float, default=0.95)
    parser.add_argument("--max-examples", type=int, default=20)
    args = parser.parse_args()

    input_files = []
    for path in args.paths:
        if path.is_dir():
            input_files.extend(sorted(path.glob("*.jsonl")))
        elif path.suffix == ".jsonl":
            input_files.append(path)

    embedding_config = load_embedding_config(args.embedding_config) if args.embeddings else {}
    reports = []
    rows_by_file = {}
    for path in input_files:
        report, deduped_rows, file_metric_rows = audit_file(path, args, embedding_config)
        reports.append(report)
        rows_by_file[report["file"]] = file_metric_rows
        if args.write_deduped:
            write_jsonl(args.deduped_dir / path.name, deduped_rows)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary_csv(args.metrics_csv, reports, rows_by_file)

    print(f"Audited {len(input_files)} file(s). Report: {args.report}")
    print(f"Metrics CSV: {args.metrics_csv}")
    if args.write_deduped:
        print(f"Deduplicated JSONL files: {args.deduped_dir}")


if __name__ == "__main__":
    main()
