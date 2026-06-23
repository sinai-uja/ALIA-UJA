import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tqdm import tqdm

from audit_dpo_data import bleu_score, chrf_score, distribution, normalize_text, stable_hash, token_count


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"_source_file": str(path), "_source_line": line_number, "_invalid_json": True})
                continue
            item["_source_file"] = str(path)
            item["_source_line"] = line_number
            rows.append(item)
    return rows


def find_input_files(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        elif path.suffix == ".jsonl":
            files.append(path)
    return [
        path
        for path in files
        if "clean" not in path.stem and "merged" not in path.stem and "removed" not in path.stem
    ]


def reject_reasons(row: dict[str, Any], args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    if row.get("_invalid_json"):
        return ["invalid_json"], {}

    prompt = normalize_text(row.get("prompt"))
    chosen = normalize_text(row.get("chosen"))
    rejected = normalize_text(row.get("rejected"))
    reasons = []

    for field, value in (("prompt", prompt), ("chosen", chosen), ("rejected", rejected)):
        if field not in row:
            reasons.append(f"missing_{field}")
        elif not value:
            reasons.append(f"empty_{field}")

    if reasons:
        return reasons, {}

    chosen_tokens = token_count(chosen)
    rejected_tokens = token_count(rejected)
    length_ratio = chosen_tokens / max(rejected_tokens, 1)
    chrf = chrf_score(chosen, rejected)
    bleu = bleu_score(chosen, rejected)

    if rejected_tokens < args.min_rejected_tokens:
        reasons.append("short_rejected")
    if length_ratio < args.min_length_ratio:
        reasons.append("length_ratio_too_low")
    if length_ratio > args.max_length_ratio:
        reasons.append("length_ratio_too_high")
    if chrf > args.max_chrf:
        reasons.append("high_chrf")
    if bleu > args.max_bleu:
        reasons.append("high_bleu")

    metrics = {
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
        "chosen_tokens": chosen_tokens,
        "rejected_tokens": rejected_tokens,
        "length_ratio": length_ratio,
        "chrf": chrf,
        "bleu": bleu,
    }
    return reasons, metrics


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in row.items() if not key.startswith("_")}
    metadata = cleaned.get("metadata")
    if isinstance(metadata, dict):
        metadata = dict(metadata)
    else:
        metadata = {}
    metadata.setdefault("source_file", row.get("_source_file"))
    metadata.setdefault("source_line", row.get("_source_line"))
    cleaned["metadata"] = metadata
    return cleaned


def removed_row(row: dict[str, Any], reasons: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    cleaned = public_row(row) if not row.get("_invalid_json") else {}
    cleaned["removal_reasons"] = reasons
    cleaned["source_file"] = row.get("_source_file")
    cleaned["source_line"] = row.get("_source_line")
    cleaned["chosen_tokens"] = metrics.get("chosen_tokens", "")
    cleaned["rejected_tokens"] = metrics.get("rejected_tokens", "")
    cleaned["length_ratio"] = metrics.get("length_ratio", "")
    cleaned["chrf"] = metrics.get("chrf", "")
    cleaned["bleu"] = metrics.get("bleu", "")
    return cleaned


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_removed_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_file",
        "source_line",
        "removal_reasons",
        "prompt_id",
        "prompt",
        "chosen",
        "rejected",
        "chosen_tokens",
        "rejected_tokens",
        "length_ratio",
        "chrf",
        "bleu",
        "metadata",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "source_file": row.get("source_file", ""),
                    "source_line": row.get("source_line", ""),
                    "removal_reasons": "|".join(row.get("removal_reasons", [])),
                    "prompt_id": row.get("prompt_id", ""),
                    "prompt": row.get("prompt", ""),
                    "chosen": row.get("chosen", ""),
                    "rejected": row.get("rejected", ""),
                    "chosen_tokens": row.get("chosen_tokens", ""),
                    "rejected_tokens": row.get("rejected_tokens", ""),
                    "length_ratio": row.get("length_ratio", ""),
                    "chrf": row.get("chrf", ""),
                    "bleu": row.get("bleu", ""),
                    "metadata": json.dumps(row.get("metadata", {}), ensure_ascii=False),
                }
            )


def write_dataset_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["prompt_id", "prompt", "chosen", "rejected", "metadata"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "prompt_id": row.get("prompt_id", ""),
                    "prompt": row.get("prompt", ""),
                    "chosen": row.get("chosen", ""),
                    "rejected": row.get("rejected", ""),
                    "metadata": json.dumps(row.get("metadata", {}), ensure_ascii=False),
                }
            )


def write_summary(path: Path, summary_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scope",
        "input_rows",
        "kept_rows",
        "removed_rows",
        "invalid_or_empty",
        "short_rejected",
        "length_ratio_too_low",
        "length_ratio_too_high",
        "high_chrf",
        "high_bleu",
        "duplicate_prompt_chosen",
        "duplicate_prompt",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)


def duplicate_row_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count for count in counts.values() if count > 1)


def write_clean_metrics(
    path: Path,
    rows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    chosen_dist = distribution([metric["chosen_tokens"] for metric in metrics])
    rejected_dist = distribution([metric["rejected_tokens"] for metric in metrics])
    ratio_dist = distribution([metric["length_ratio"] for metric in metrics])
    chrf_dist = distribution([metric["chrf"] for metric in metrics])
    bleu_dist = distribution([metric["bleu"] for metric in metrics])
    prompt_hashes = [stable_hash(metric["prompt"]) for metric in metrics]
    prompt_chosen_hashes = [stable_hash(metric["prompt"], metric["chosen"]) for metric in metrics]

    row = {
        "scope": "clean_dataset",
        "total_rows": len(rows),
        "usable_rows": len(metrics),
        "empty_or_invalid_rows": len(rows) - len(metrics),
        "short_rejected_count": sum(metric["rejected_tokens"] < args.min_rejected_tokens for metric in metrics),
        "length_ratio_too_low_count": sum(metric["length_ratio"] < args.min_length_ratio for metric in metrics),
        "length_ratio_too_high_count": sum(metric["length_ratio"] > args.max_length_ratio for metric in metrics),
        "high_chrf_count": sum(metric["chrf"] > args.max_chrf for metric in metrics),
        "high_bleu_count": sum(metric["bleu"] > args.max_bleu for metric in metrics),
        "duplicate_prompt_chosen_rows": duplicate_row_count(prompt_chosen_hashes),
        "duplicate_prompt_rows": duplicate_row_count(prompt_hashes),
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
    }

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean and merge DPO JSONL files into one filtered dataset.")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("dpo_data")], help="JSONL file(s) or directories to clean.")
    parser.add_argument("--output", type=Path, default=Path("dpo_data/dpo_dataset_clean_merged.jsonl"))
    parser.add_argument("--output-csv", type=Path, default=Path("dpo_data/dpo_dataset_clean_merged.csv"))
    parser.add_argument("--removed-output", type=Path, default=Path("dpo_data/dpo_dataset_removed.jsonl"))
    parser.add_argument("--removed-csv", type=Path, default=Path("dpo_data/dpo_dataset_removed.csv"))
    parser.add_argument("--summary-csv", type=Path, default=Path("dpo_data/dpo_clean_summary.csv"))
    parser.add_argument("--clean-metrics-csv", type=Path, default=Path("dpo_data/dpo_clean_metrics.csv"))
    parser.add_argument("--min-rejected-tokens", type=int, default=20)
    parser.add_argument("--min-length-ratio", type=float, default=0.25)
    parser.add_argument("--max-length-ratio", type=float, default=4.0)
    parser.add_argument("--max-chrf", type=float, default=0.85)
    parser.add_argument("--max-bleu", type=float, default=0.60)
    parser.add_argument("--dedup-prompt", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dedup-prompt-chosen", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    input_files = find_input_files(args.paths)
    kept_rows = []
    kept_metrics = []
    removed_rows = []
    seen_prompt = set()
    seen_prompt_chosen = set()
    summaries = []
    all_counts = Counter()

    for path in input_files:
        rows = load_jsonl(path)
        counts = Counter(input_rows=len(rows))

        for row in tqdm(rows, desc=f"Cleaning {path.name}", leave=False):
            reasons, metrics = reject_reasons(row, args)
            if reasons:
                counts.update(["invalid_or_empty" if reason.startswith(("invalid", "missing", "empty")) else reason for reason in reasons])
                removed_rows.append(removed_row(row, reasons, metrics))
                continue

            prompt_hash = stable_hash(metrics["prompt"])
            prompt_chosen_hash = stable_hash(metrics["prompt"], metrics["chosen"])
            if args.dedup_prompt_chosen and prompt_chosen_hash in seen_prompt_chosen:
                counts.update(["duplicate_prompt_chosen"])
                removed_rows.append(removed_row(row, ["duplicate_prompt_chosen"], metrics))
                continue
            if args.dedup_prompt and prompt_hash in seen_prompt:
                counts.update(["duplicate_prompt"])
                removed_rows.append(removed_row(row, ["duplicate_prompt"], metrics))
                continue

            seen_prompt_chosen.add(prompt_chosen_hash)
            seen_prompt.add(prompt_hash)
            kept_rows.append(public_row(row))
            kept_metrics.append(metrics)
            counts.update(["kept_rows"])

        counts["removed_rows"] = counts["input_rows"] - counts["kept_rows"]
        summaries.append({"scope": str(path), **{key: counts[key] for key in (
            "input_rows",
            "kept_rows",
            "removed_rows",
            "invalid_or_empty",
            "short_rejected",
            "length_ratio_too_low",
            "length_ratio_too_high",
            "high_chrf",
            "high_bleu",
            "duplicate_prompt_chosen",
            "duplicate_prompt",
        )}})
        all_counts.update(counts)

    all_counts["kept_rows"] = len(kept_rows)
    all_counts["removed_rows"] = all_counts["input_rows"] - all_counts["kept_rows"]
    summaries.append({"scope": "ALL", **{key: all_counts[key] for key in (
        "input_rows",
        "kept_rows",
        "removed_rows",
        "invalid_or_empty",
        "short_rejected",
        "length_ratio_too_low",
        "length_ratio_too_high",
        "high_chrf",
        "high_bleu",
        "duplicate_prompt_chosen",
        "duplicate_prompt",
    )}})

    write_jsonl(args.output, kept_rows)
    write_dataset_csv(args.output_csv, kept_rows)
    write_jsonl(args.removed_output, removed_rows)
    write_removed_csv(args.removed_csv, removed_rows)
    write_summary(args.summary_csv, summaries)
    write_clean_metrics(args.clean_metrics_csv, kept_rows, kept_metrics, args)
    print(f"Wrote clean dataset: {args.output} ({len(kept_rows)} rows)")
    print(f"Wrote clean dataset CSV: {args.output_csv}")
    print(f"Wrote removed rows: {args.removed_output} ({len(removed_rows)} rows)")
    print(f"Wrote removed rows CSV: {args.removed_csv}")
    print(f"Wrote cleaning summary: {args.summary_csv}")
    print(f"Wrote clean dataset metrics: {args.clean_metrics_csv}")


if __name__ == "__main__":
    main()
