#!/usr/bin/env python3
"""Filter and deduplicate JSONL comments (YouTube / TikTok) with datatrove.

This pipeline follows the FineWeb curation flow.

The output preserves only the original JSONL fields that are explicitly
serialized by the writer: ``id`` and ``text``. Documents are only filtered;
their content is never modified except for mention anonymization.

Pipeline (4 stages):

  Stage 1 - Filtering and intermediate write
      JsonlReader
      -> LambdaFilter           (drops emoji-only comments)
      -> LanguageFilter         (fastText, only "es", score >= language_threshold)
      -> GopherRepetitionFilter (drops texts with highly repeated n-grams)
      -> GopherQualityFilter    (lexical quality, adapted to short texts)
      -> LambdaFilter           (spam: URLs, mentions, non-alpha chars)
      -> JsonlWriter            -> curated/<platform>/<name>/intermediate/

  Stages 2-4 - MinHash deduplication (near-duplicate, FineWeb style)
      Stage 2: MinhashDedupSignature   (computes document signatures)
      Stage 3: MinhashDedupBuckets + MinhashDedupCluster (finds clusters)
      Stage 4: JsonlReader -> MinhashDedupFilter -> JsonlWriter (final output)

The final output contains only ``id`` and ``text``, without compression and
without metadata.

After all datasets are processed, the script also writes a single combined
JSONL at the curated root with ``id``, ``source``, and ``text``.

Usage:
    python filter_curate.py --config config.yaml [--workers N] [--tasks N] [--no-dedup] [--verbose]

Dependencies:
    # Pinned installs recommended to avoid fastText / NumPy incompatibilities
    pip install 'datatrove[all]==0.9.0' pyyaml 'numpy<2' fasttext-numpy2-wheel==0.9.2 regex
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# datatrove - mandatory import for this workflow
# ---------------------------------------------------------------------------
try:
    from datatrove.executor.local import LocalPipelineExecutor
    from datatrove.pipeline.dedup import MinhashDedupSignature
    from datatrove.pipeline.dedup.minhash import (
        MinhashConfig,
        MinhashDedupBuckets,
        MinhashDedupCluster,
        MinhashDedupFilter,
    )
    from datatrove.pipeline.filters import (
        GopherQualityFilter,
        GopherRepetitionFilter,
        LanguageFilter,
        LambdaFilter,
    )
    from datatrove.pipeline.readers import JsonlReader
    from datatrove.pipeline.writers.jsonl import JsonlWriter
    from datatrove.data import Document
    from datatrove.utils.hashing import HashConfig

    HAS_DATATROVE = True
except ImportError:
    HAS_DATATROVE = False

# ---------------------------------------------------------------------------
# Emoji regex - use `regex` if available (supports \\p{} Unicode)
# ---------------------------------------------------------------------------
try:
    import regex as _re_mod
    _UNICODE_RE = True
except ImportError:
    import re as _re_mod  # type: ignore
    _UNICODE_RE = False

EMOJI_RE = _re_mod.compile(
    r"[\U0001F600-\U0001F64F"
    r"\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F1E0-\U0001F1FF"
    r"\u2600-\u26FF\u2700-\u27BF"
    r"\U0001F900-\U0001F9FF"
    r"\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF]+",
    flags=_re_mod.UNICODE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtering utilities shared by datatrove and the fallback
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict[str, Any]:
    """Load YAML configuration from a file.

    Args:
        path: Path to a YAML config file.

    Returns:
        Parsed configuration mapping.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the YAML cannot be parsed.
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_only_emojis(text: str) -> bool:
    """Return ``True`` if the text contains only emojis and whitespace."""
    if not text or not text.strip():
        return False
    if _UNICODE_RE:
        cleaned = _re_mod.sub(r"[\p{Z}\p{P}\p{S}]", "", EMOJI_RE.sub("", text))
    else:
        cleaned = re.sub(r"\s", "", EMOJI_RE.sub("", text))
    return cleaned == ""


def _count_urls(text: str) -> int:
    return len(re.findall(r"https?://\S+|www\.\S+", text))


def _count_mentions(text: str) -> int:
    return len(re.findall(r"@\w+", text))


def _has_repeated_sequences(text: str, threshold: int) -> bool:
    return bool(re.search(r"(.)\1{" + str(threshold) + r",}", text))


def _nonalpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    non_alpha = sum(1 for c in text if not c.isalpha() and not c.isspace())
    return non_alpha / max(1, len(text))


def anonymize_mentions(text: str) -> str:
    """Replace mention-like tokens with ``@usuario``.

    Args:
        text: Input text.

    Returns:
        Text with mention-like tokens normalized.
    """
    if not text:
        return text
    return re.sub(r"@[\w\.-]+", "@usuario", text)


def anonymize_document_text(doc: "Document") -> bool:
    """Apply mention anonymization in place and keep the document flowing.

    Args:
        doc: Datatrove document to mutate.

    Returns:
        Always ``True`` so the document continues through the pipeline.
    """

    doc.text = anonymize_mentions(doc.text)
    return True


def id_text_adapter(_self: Any, document: "Document") -> dict[str, str]:
    """Serialize datatrove documents as plain JSON objects.

    Args:
        _self: Bound writer instance, unused.
        document: Datatrove document to serialize.

    Returns:
        A JSON-serializable mapping with only ``id`` and ``text``.
    """

    return {"id": document.id, "text": document.text}


def count_jsonl_documents(folder: Path) -> int:
    """Count records in all JSONL and JSONL.GZ files under a folder.

    Args:
        folder: Folder to scan recursively.

    Returns:
        Number of JSONL rows found.
    """

    total = 0
    if not folder.exists():
        return total
    for file_path in folder.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name.endswith(".jsonl"):
            opener = open
        elif file_path.name.endswith(".jsonl.gz"):
            opener = gzip.open
        else:
            continue
        with opener(file_path, "rt", encoding="utf-8", errors="ignore") as handle:
            total += sum(1 for _ in handle)
    return total


def build_combined_jsonl(curated_root: Path, cfg: dict[str, Any]) -> tuple[Path, int]:
    """Combine all per-dataset outputs into one curated JSONL file.

    Args:
        curated_root: Base curated directory that contains platform folders.
        cfg: Loaded pipeline configuration.

    Returns:
        A tuple with the combined output path and the number of merged rows.
    
    Raises:
        OSError: If writing to the combined file fails.
    """

    combined_path = curated_root / "curated.jsonl"
    combined_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with combined_path.open("w", encoding="utf-8") as output_handle:
        for platform, sources in cfg.get("sources", {}).items():
            for src in sources:
                method = src["name"]
                output_dir = curated_root / platform / method / "output"
                if not output_dir.exists():
                    logger.warning("Output folder missing, skipping combined export: %s", output_dir)
                    continue

                for jsonl_file in sorted(output_dir.rglob("*.jsonl")):
                    with jsonl_file.open("r", encoding="utf-8", errors="ignore") as input_handle:
                        for line in input_handle:
                            line = line.strip()
                            if not line:
                                continue
                            record = json.loads(line)
                            combined_record = {
                                "id": record.get("id"),
                                "source": platform,
                                "text": record.get("text", ""),
                            }
                            output_handle.write(json.dumps(combined_record, ensure_ascii=False) + "\n")
                            total += 1

    return combined_path, total


# ---------------------------------------------------------------------------
# Stage 1: datatrove filtering
# ---------------------------------------------------------------------------

def _build_stage1(
    in_folder: str,
    intermediate_folder: str,
    removed_folder: str,
    cfg: dict[str, Any],
    workers: int,
    tasks: int,
    id_key: str = "id",
) -> "LocalPipelineExecutor":
    """Build the first-stage filtering pipeline.

    Args:
        in_folder: Input folder containing the source JSONL files.
        intermediate_folder: Folder where filtered rows are written.
        removed_folder: Folder used for excluded rows.
        cfg: Loaded pipeline configuration.
        workers: Number of parallel workers to use.
        tasks: Number of datatrove tasks per source.
        id_key: Document identifier field name.

    Returns:
        A configured datatrove pipeline executor for stage 1.
    """
    f = cfg.get("filter", {})
    lang_threshold = f.get("language_threshold", 0.7)
    max_urls = f.get("max_urls", 1)
    max_mentions = f.get("max_mentions", 3)
    max_rep = f.get("max_repeated_seq", 10)
    max_nonalpha = f.get("max_nonalpha_ratio", 0.6)

    def _not_spam(doc: "Document") -> bool:
        t = doc.text
        return (
            _count_urls(t) <= max_urls
            and _count_mentions(t) <= max_mentions
            and not _has_repeated_sequences(t, max_rep)
            and _nonalpha_ratio(t) <= max_nonalpha
        )

    pipeline = [
        JsonlReader(
            data_folder=str(Path(in_folder).parent),
            glob_pattern=Path(in_folder).name,
            text_key="text",
            id_key=id_key,
        ),
        # 1. Drop emoji-only comments.
        LambdaFilter(
            lambda doc: not is_only_emojis(doc.text),
            exclusion_writer=JsonlWriter(f"{removed_folder}/1_only_emojis"),
        ),
        # 2. Spanish language detection with fastText (score >= language_threshold)
        LanguageFilter(
            languages=("es",),
            language_threshold=lang_threshold,
            exclusion_writer=JsonlWriter(
                f"{removed_folder}/2_non_spanish",
                output_filename="${language}/${rank}.jsonl",
            ),
        ),
        # 5. Heuristic spam filter (URLs, mentions, non-alpha chars)
        LambdaFilter(
            _not_spam,
            exclusion_writer=JsonlWriter(f"{removed_folder}/3_spam"),
        ),
        # 6. Mandatory mention anonymization before persisting
        LambdaFilter(
            anonymize_document_text,
        ),
        # Intermediate write (input for the MinHash stages)
        JsonlWriter(
            output_folder=intermediate_folder,
            output_filename="${rank}.jsonl",
            compression=None,
            adapter=id_text_adapter,
        ),
    ]

    return LocalPipelineExecutor(
        pipeline=pipeline,
        logging_dir=f"{removed_folder}/../logs/stage1",
        tasks=tasks,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Stages 2-4: MinHash deduplication
# ---------------------------------------------------------------------------

def _build_minhash_stages(
    intermediate_folder: str,
    minhash_base: str,
    output_folder: str,
    logs_base: str,
    workers: int,
    tasks: int,
    num_buckets: int = 8,
    hashes_per_bucket: int = 8,
) -> tuple["LocalPipelineExecutor", "LocalPipelineExecutor", "LocalPipelineExecutor"]:
    """Build the MinHash deduplication executors.

    Args:
        intermediate_folder: Folder with the stage 1 JSONL output.
        minhash_base: Base directory for MinHash artifacts.
        output_folder: Final output folder for deduplicated rows.
        logs_base: Base directory for stage logs.
        workers: Number of parallel workers to use.
        tasks: Number of datatrove tasks per source.
        num_buckets: Number of MinHash buckets.
        hashes_per_bucket: Number of hashes per bucket.

    Returns:
        A tuple with the stage 2, stage 3, and stage 4 executors.
    """
    minhash_config = MinhashConfig(
        hash_config=HashConfig(precision=64),
        num_buckets=num_buckets,
        hashes_per_bucket=hashes_per_bucket,
    )

    stage2 = LocalPipelineExecutor(
        pipeline=[
            JsonlReader(data_folder=intermediate_folder),
            MinhashDedupSignature(
                output_folder=f"{minhash_base}/signatures",
                config=minhash_config,
            ),
        ],
        tasks=tasks,
        workers=workers,
        logging_dir=f"{logs_base}/stage2_signatures",
    )

    stage3 = LocalPipelineExecutor(
        pipeline=[
            MinhashDedupBuckets(
                input_folder=f"{minhash_base}/signatures",
                output_folder=f"{minhash_base}/buckets",
                config=minhash_config,
            ),
            MinhashDedupCluster(
                input_folder=f"{minhash_base}/buckets",
                output_folder=f"{minhash_base}/clusters",
                config=minhash_config,
            ),
        ],
        tasks=1,  # MinhashDedupCluster requires world_size=1; cannot parallelize clustering.
        workers=1,  # Must be sequential.
        logging_dir=f"{logs_base}/stage3_cluster",
    )

    stage4 = LocalPipelineExecutor(
        pipeline=[
            JsonlReader(data_folder=intermediate_folder),
            MinhashDedupFilter(
                input_folder=f"{minhash_base}/clusters",
                exclusion_writer=JsonlWriter(f"{minhash_base}/removed_duplicates"),
            ),
            JsonlWriter(
                output_folder=output_folder,
                output_filename="${rank}.jsonl",
                compression=None,
                adapter=id_text_adapter,
            ),
        ],
        tasks=tasks,
        workers=workers,
        logging_dir=f"{logs_base}/stage4_dedup_filter",
    )

    return stage2, stage3, stage4


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments and run the curation pipeline."""
    parser = argparse.ArgumentParser(
        description="Filter and deduplicate JSONL comments with datatrove (FineWeb style)."
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for LocalPipelineExecutor",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=1,
        help="Number of datatrove tasks per source",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Skip the MinHash deduplication stages",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    cfg = load_config(args.config)
    base_in = Path(cfg["data_base_path"])
    f_cfg = cfg.get("filter", {})
    curated = Path(f_cfg["curated_base_path"])
    if not HAS_DATATROVE:
        raise RuntimeError(
            "datatrove is required for this workflow. Install it with: "
            "pip install 'datatrove[all]'"
        )

    overall: dict[str, Any] = {}

    for platform, sources in cfg.get("sources", {}).items():
        for src in sources:
            name = src["name"]
            in_path = base_in / src["path"]

            if not in_path.exists():
                logger.info("Source not found, skipping: %s", in_path)
                continue

            source_key = f"{platform}/{name}"
            out_base   = curated / platform / name
            logs_base  = str(out_base / "logs")

            logger.info("Processing: %s", source_key)

            id_key = "cid" if platform == "youtube" else "id"

            intermediate = str(out_base / "intermediate")
            removed = str(out_base / "removed")
            final_output = str(out_base / "output")
            minhash_base = str(out_base / "minhash")

            # Stage 1 - filtering.
            _build_stage1(
                in_folder=str(in_path),
                intermediate_folder=intermediate,
                removed_folder=removed,
                cfg=cfg,
                workers=args.workers,
                tasks=args.tasks,
                id_key=id_key,
            ).run()

            if not args.no_dedup:
                # Skip MinHash only when stage 1 produced no files.
                inter_p = Path(intermediate)
                if count_jsonl_documents(inter_p) == 0:
                    logger.warning(
                        "No intermediate files in %s — skipping MinHash dedup",
                        inter_p,
                    )
                    output_dir = inter_p
                else:
                    # Stages 2-4 - MinHash deduplication.
                    minhash_cfg = cfg.get("minhash", {})
                    num_buckets = minhash_cfg.get("num_buckets", 8)
                    hashes_per_bucket = minhash_cfg.get("hashes_per_bucket", 8)
                    
                    # Validate that num_buckets is compatible with the number of workers.
                    # datatrove requires: len(dup_files) % num_buckets == 0
                    if args.tasks > 0:
                        if num_buckets % args.workers != 0 and args.workers % num_buckets != 0:
                            logger.warning(
                                "num_buckets=%d may not divide evenly with workers=%d. "
                                "Consider setting num_buckets to a divisor of workers "
                                "(e.g., %d)",
                                num_buckets,
                                args.workers,
                                args.workers,
                            )
                    
                    stage2, stage3, stage4 = _build_minhash_stages(
                        intermediate_folder=intermediate,
                        minhash_base=minhash_base,
                        output_folder=final_output,
                        logs_base=logs_base,
                        workers=args.workers,
                        tasks=args.tasks,
                        num_buckets=num_buckets,
                        hashes_per_bucket=hashes_per_bucket,
                    )
                    stage2.run()
                    stage3.run()
                    stage4.run()
                    output_dir = Path(final_output)
            else:
                output_dir = Path(intermediate)

            kept = count_jsonl_documents(output_dir)
            overall[source_key] = {
                "status": "datatrove",
                "dedup": not args.no_dedup,
                "kept": kept,
                "output": str(output_dir),
            }

    # Global summary.
    combined_path, combined_count = build_combined_jsonl(curated, cfg)
    summary_path = curated / "filter_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                **overall,
                "__combined__": {
                    "path": str(combined_path),
                    "kept": combined_count,
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("Summary saved to %s", summary_path)

    if args.verbose:
        logger.info(json.dumps(overall, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()