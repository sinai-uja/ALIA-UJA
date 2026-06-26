#!/usr/bin/env python3
"""Annotate a single hate-speech JSONL file with local vLLM models.

The input JSONL must contain records with at least `id` and `text` fields.
The `source` metadata field is propagated into output records.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import outlines
import torch
import yaml
from json_repair import repair_json
from pydantic import BaseModel, Field
from vllm import LLM, SamplingParams


FAILED_SENTINEL = "__FAILED__"
EXHAUSTED_SENTINEL = "__EXHAUSTED__"
_PIPELINE_ONLY_KEYS: frozenset[str] = frozenset({"batch_size"})


class HateClass(BaseModel):
    """Structured response schema produced by the model."""

    is_hate: bool = Field(
        description="True si el comentario constituye discurso de odio, False en caso contrario"
    )
    explanation: str = Field(
        description="Redacta detalladamente el analisis que justifica la decision"
    )


def setup_logging(log_file: Path) -> logging.Logger:
    """Configures file and console logging and returns the module logger."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return logging.getLogger(__name__)


def load_config(path: Path) -> dict[str, Any]:
    """Loads a YAML config file and validates it is a mapping."""
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Invalid config format in {path}: expected a mapping")
    return loaded


def resolve_prompt_path(config_path: Path, config: dict[str, Any]) -> Path:
    """Resolves and validates the unique prompt path declared in config."""
    prompt_value = str(config.get("prompt_path", "")).strip()
    if not prompt_value:
        raise ValueError("Config missing required key 'prompt_path'")

    prompt_path = Path(prompt_value)
    if not prompt_path.is_absolute():
        prompt_path = (config_path.parent / prompt_path).resolve()

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    if prompt_path.suffix.lower() != ".md":
        raise ValueError(f"Prompt file must be a Markdown file (.md): {prompt_path}")
    return prompt_path


def _sanitize_comment(text: str) -> str:
    """Normalizes comments to reduce prompt-formatting issues."""
    if not isinstance(text, str):
        return ""
    text = text.replace("\u201c", "'").replace("\u201d", "'")
    text = text.replace('"', "'")
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return "".join(c for c in text if ord(c) >= 32)


def _resolve_model_batch_size(config: dict[str, Any], model_alias: str) -> int:
    """Returns the required per-model batch size from config overrides."""
    overrides = config.get("model_params_overrides", {}) or {}
    model_cfg = overrides.get(model_alias)
    if not isinstance(model_cfg, dict) or "batch_size" not in model_cfg:
        raise ValueError(
            "Missing per-model batch_size for "
            f"'{model_alias}' in model_params_overrides"
        )
    return int(model_cfg["batch_size"])


def _with_rope_scaling_compat(
    model_path: str,
    params: dict[str, Any],
    logger: logging.Logger,
) -> dict[str, Any]:
    """Adds a rope_scaling compatibility override when needed."""
    cfg_path = Path(model_path) / "config.json"
    if not cfg_path.exists():
        return params

    try:
        model_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return params

    rope_scaling = model_cfg.get("rope_scaling")
    if not isinstance(rope_scaling, dict):
        return params
    if "rope_type" in rope_scaling or "type" not in rope_scaling:
        return params

    fixed_rope_scaling = dict(rope_scaling)
    fixed_rope_scaling["rope_type"] = fixed_rope_scaling["type"]

    out = dict(params)
    hf_overrides = out.get("hf_overrides")
    hf_overrides = dict(hf_overrides) if isinstance(hf_overrides, dict) else {}

    existing_rope = hf_overrides.get("rope_scaling")
    merged_rope = dict(fixed_rope_scaling)
    if isinstance(existing_rope, dict):
        merged_rope.update(existing_rope)

    hf_overrides["rope_scaling"] = merged_rope
    out["hf_overrides"] = hf_overrides

    logger.warning(
        "Applied rope_scaling compatibility override for %s (type->rope_type)",
        model_path,
    )
    return out


def load_input_jsonl(path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Loads input JSONL and returns comment text plus source metadata."""
    comments: dict[str, str] = {}
    meta: dict[str, dict[str, str]] = {}

    if not path.exists():
        raise FileNotFoundError(f"Input JSONL not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line_str = line.strip()
            if not line_str:
                continue

            try:
                rec = json.loads(line_str)
            except Exception:
                try:
                    rec = json.loads(repair_json(line_str))
                except Exception:
                    continue

            id_ = str(rec.get("id", "")).strip()
            if not id_:
                continue

            value = rec.get("text", "")
            comment = value if isinstance(value, str) else str(value)
            comments[id_] = str(comment)
            meta[id_] = {
                "source": str(rec.get("source", "")),
            }
    return comments, meta


class JsonlStore:
    """Persistent index-backed store for one model output JSONL file."""

    def __init__(
        self,
        path: Path,
        model_alias: str,
        logger: logging.Logger,
    ) -> None:
        self.path = path
        self.model_alias = model_alias
        self.logger = logger
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index: dict[tuple[str, str], dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _key(source: str, id_: str) -> tuple[str, str]:
        """Builds the stable deduplication key for output records."""
        return source, id_

    @staticmethod
    def _is_valid(record: dict[str, Any]) -> bool:
        """Returns True when the record has a valid boolean label."""
        return isinstance(record.get("is_hate"), bool)

    def _load(self) -> None:
        """Loads existing JSONL entries into memory, keeping best records."""
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    rec = json.loads(line_str)
                except Exception:
                    continue

                if rec.get("model_alias") != self.model_alias:
                    continue

                source = str(rec.get("source", ""))
                id_ = str(rec.get("id", ""))
                if not all((source, id_)):
                    continue

                key = self._key(source, id_)
                old = self.index.get(key)
                if old is None or (not self._is_valid(old) and self._is_valid(rec)):
                    self.index[key] = rec

        self.logger.info(
            "JSONL loaded model=%s path=%s indexed=%d",
            self.model_alias,
            self.path,
            len(self.index),
        )

    def pending_ids(
        self,
        meta: dict[str, dict[str, str]],
        all_ids: set[str],
    ) -> dict[str, list[str]]:
        """Returns IDs pending annotation, split by missing/failed."""
        missing = self.missing_ids(meta, all_ids)
        failed = self.failed_ids(meta, all_ids)
        return {"missing": missing, "failed": failed}

    def missing_ids(
        self,
        meta: dict[str, dict[str, str]],
        all_ids: set[str],
    ) -> list[str]:
        """Returns IDs that have no stored record yet."""
        missing: list[str] = []
        for id_ in all_ids:
            rec_meta = meta.get(id_, {})
            source = str(rec_meta.get("source", ""))
            if not source:
                continue
            if self._key(source, id_) not in self.index:
                missing.append(id_)
        return missing

    def failed_ids(
        self,
        meta: dict[str, dict[str, str]],
        all_ids: set[str],
    ) -> list[str]:
        """Returns IDs with non-valid labels that are still retryable."""
        out: list[str] = []
        for id_ in all_ids:
            rec_meta = meta.get(id_, {})
            source = str(rec_meta.get("source", ""))
            if not source:
                continue
            key = self._key(source, id_)
            rec = self.index.get(key)
            if rec is not None and not self._is_valid(rec):
                if rec.get("explanation") != EXHAUSTED_SENTINEL:
                    out.append(id_)
        return out

    def append(self, record: dict[str, Any]) -> None:
        """Appends one record to disk and updates the in-memory index."""
        source = str(record.get("source", ""))
        id_ = str(record.get("id", ""))
        if not all((source, id_)):
            return

        key = self._key(source, id_)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.index[key] = record

    def remove_failed(
        self,
        meta: dict[str, dict[str, str]],
        ids: list[str],
    ) -> None:
        """Deletes selected failed IDs from both index and file."""
        keys_to_remove: set[tuple[str, str]] = set()
        for id_ in ids:
            rec_meta = meta.get(id_, {})
            source = str(rec_meta.get("source", ""))
            if not source:
                continue
            keys_to_remove.add(self._key(source, id_))

        for key in keys_to_remove:
            self.index.pop(key, None)

        if not self.path.exists():
            return

        tmp_path = self.path.with_suffix(".tmp")
        kept = 0
        with self.path.open("r", encoding="utf-8") as src, tmp_path.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    rec = json.loads(line_str)
                except Exception:
                    dst.write(line)
                    continue

                key = self._key(
                    str(rec.get("source", "")),
                    str(rec.get("id", "")),
                )
                if key in keys_to_remove:
                    continue
                dst.write(line)
                kept += 1

        tmp_path.replace(self.path)
        self.logger.info(
            "JSONL rewritten after removing %d FAILED records (kept=%d)",
            len(ids),
            kept,
        )


def process_batch(
    model: Any,
    tokenizer: Any,
    template: Any,
    comments: list[str],
    sampling_params: SamplingParams,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """Runs inference for a batch and returns parsed structured responses."""
    safe_comments = [_sanitize_comment(c) for c in comments]
    base_prompts = [template(comment=c) for c in safe_comments]

    prompts: list[str] = []
    chat_template = getattr(tokenizer, "chat_template", None)
    apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
    for base_prompt in base_prompts:
        if callable(apply_chat_template) and chat_template is not None:
            try:
                chat_prompt = apply_chat_template(
                    [{"role": "user", "content": base_prompt}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
                prompts.append(chat_prompt)
            except Exception:
                prompts.append(base_prompt)
        else:
            prompts.append(base_prompt)

    results: list[dict[str, Any]] = [
        {"is_hate": None, "explanation": FAILED_SENTINEL} for _ in comments
    ]

    try:
        responses = model.generate_batch(
            prompts,
            output_type=HateClass,
            sampling_params=sampling_params,
        )
        for i, response in enumerate(responses):
            text = response[0] if isinstance(response, list) else response
            try:
                obj = HateClass.model_validate_json(repair_json(text))
                results[i] = {
                    "is_hate": obj.is_hate,
                    "explanation": obj.explanation,
                }
            except Exception as exc:
                logger.warning("PARSE FAILED | idx=%d | error=%s", i, exc)
    except Exception as exc:
        logger.warning(
            "BATCH FAILED | batch_size=%d | error=%s",
            len(comments),
            exc,
        )
        for i, prompt in enumerate(prompts):
            try:
                one = model.generate_batch(
                    [prompt],
                    output_type=HateClass,
                    sampling_params=sampling_params,
                )
                text = one[0][0] if isinstance(one[0], list) else one[0]
                obj = HateClass.model_validate_json(repair_json(text))
                results[i] = {
                    "is_hate": obj.is_hate,
                    "explanation": obj.explanation,
                }
            except Exception as exc_individual:
                logger.warning(
                    "INDIVIDUAL FAILED | idx=%d | error=%s",
                    i,
                    exc_individual,
                )

    return results


def _annotate_ids(
    ids: list[str],
    comments: dict[str, str],
    meta: dict[str, dict[str, str]],
    model: Any,
    tokenizer: Any,
    template: Any,
    sampling_params: SamplingParams,
    batch_size: int,
    dataset: str,
    split: str,
    model_alias: str,
    jsonl_store: JsonlStore,
    logger: logging.Logger,
    pass_label: str,
) -> int:
    """Annotates a list of IDs and persists the generated records."""
    recovered = 0
    total = len(ids)
    processed = 0

    for batch_start in range(0, total, batch_size):
        batch_ids = ids[batch_start : batch_start + batch_size]
        batch_comments = [comments[id_] for id_ in batch_ids]

        batch_results = process_batch(
            model=model,
            tokenizer=tokenizer,
            template=template,
            comments=batch_comments,
            sampling_params=sampling_params,
            logger=logger,
        )

        for id_, res in zip(batch_ids, batch_results):
            rec_meta = meta.get(id_, {})
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "model_alias": model_alias,
                "source": rec_meta.get("source", ""),
                "id": id_,
                "text": comments[id_],
                "is_hate": res.get("is_hate"),
                "explanation": str(res.get("explanation", FAILED_SENTINEL)),
            }
            jsonl_store.append(record)
            if isinstance(res.get("is_hate"), bool):
                recovered += 1

        processed += len(batch_ids)
        logger.info(
            "%s | %s | %s/%s processed=%d/%d recovered_in_pass=%d",
            pass_label,
            model_alias,
            dataset,
            split,
            processed,
            total,
            recovered,
        )

    return recovered


def run_model_on_input(
    input_path: Path,
    template: Any,
    model_alias: str,
    model: Any,
    tokenizer: Any,
    base_sampling_cfg: dict[str, Any],
    sampling_params: SamplingParams,
    batch_size: int,
    retry_failed_rounds: int,
    jsonl_store: JsonlStore,
    logger: logging.Logger,
) -> None:
    """Runs one model on the input JSONL, including retry logic."""
    dataset = "collected"
    split = input_path.stem

    comments, meta = load_input_jsonl(input_path)
    all_ids = set(comments.keys())

    pending = jsonl_store.pending_ids(meta, all_ids)
    logger.info(
        "STATUS | %s | %s/%s missing=%d failed=%d total=%d",
        model_alias,
        dataset,
        split,
        len(pending["missing"]),
        len(pending["failed"]),
        len(all_ids),
    )

    missing = jsonl_store.missing_ids(meta, all_ids)
    logger.info(
        "MAIN PASS | %s | %s/%s missing=%d",
        model_alias,
        dataset,
        split,
        len(missing),
    )
    if missing:
        _annotate_ids(
            ids=missing,
            comments=comments,
            meta=meta,
            model=model,
            tokenizer=tokenizer,
            template=template,
            sampling_params=sampling_params,
            batch_size=batch_size,
            dataset=dataset,
            split=split,
            model_alias=model_alias,
            jsonl_store=jsonl_store,
            logger=logger,
            pass_label="MAIN",
        )

    consecutive_no_progress = 0
    max_no_progress = 2

    for retry_round in range(max(0, retry_failed_rounds)):
        failed = jsonl_store.failed_ids(meta, all_ids)
        if not failed:
            logger.info(
                "RETRY | %s | %s/%s no FAILED records, stopping.",
                model_alias,
                dataset,
                split,
            )
            break

        logger.info(
            "RETRY round=%d | %s | %s/%s failed=%d",
            retry_round + 1,
            model_alias,
            dataset,
            split,
            len(failed),
        )

        jsonl_store.remove_failed(meta, failed)

        retry_cfg = dict(base_sampling_cfg)
        retry_cfg["seed"] = random.randint(0, 2**31 - 1)
        retry_params = SamplingParams(**retry_cfg)

        recovered = _annotate_ids(
            ids=failed,
            comments=comments,
            meta=meta,
            model=model,
            tokenizer=tokenizer,
            template=template,
            sampling_params=retry_params,
            batch_size=batch_size,
            dataset=dataset,
            split=split,
            model_alias=model_alias,
            jsonl_store=jsonl_store,
            logger=logger,
            pass_label=f"RETRY-{retry_round + 1}",
        )

        if recovered == 0:
            consecutive_no_progress += 1
            logger.warning(
                "RETRY round=%d | %s | %s/%s recovered 0 rows "
                "(consecutive_no_progress=%d/%d).",
                retry_round + 1,
                model_alias,
                dataset,
                split,
                consecutive_no_progress,
                max_no_progress,
            )
            if consecutive_no_progress >= max_no_progress:
                logger.warning(
                    "RETRY | %s | %s/%s stopping after %d consecutive rounds "
                    "without progress.",
                    model_alias,
                    dataset,
                    split,
                    max_no_progress,
                )
                break
        else:
            consecutive_no_progress = 0

    still_failed = jsonl_store.failed_ids(meta, all_ids)
    if still_failed:
        logger.error(
            "EXHAUSTED | %s | %s/%s %d IDs permanently failed: %s",
            model_alias,
            dataset,
            split,
            len(still_failed),
            still_failed,
        )
        jsonl_store.remove_failed(meta, still_failed)
        for id_ in still_failed:
            jsonl_store.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "model_alias": model_alias,
                    "source": meta.get(id_, {}).get("source", ""),
                    "id": id_,
                    "text": comments[id_],
                    "is_hate": None,
                    "explanation": EXHAUSTED_SENTINEL,
                }
            )


def parse_args() -> argparse.Namespace:
    """Parses CLI arguments for annotation execution."""
    parser = argparse.ArgumentParser(
        description="Annotate a single collected JSONL with local vLLM models"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("PATH/TO/CONFIG/tag_config.yaml"),
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        required=True,
        help="Path to the input collected JSONL file",
    )
    parser.add_argument(
        "--jsonl-dir",
        type=Path,
        required=True,
        help="Directory where per-model JSONL annotation files are stored",
    )
    parser.add_argument("--only-models", default=None, metavar="ALIAS,...")
    parser.add_argument("--retry-failed-rounds", type=int, default=5)
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("PATH/TO/LOGS/tag_process.log"),
    )
    return parser.parse_args()


def main() -> None:
    """Program entrypoint."""
    args = parse_args()
    logger = setup_logging(args.log_file)

    config_path = args.config.resolve()
    config = load_config(config_path)

    prompt_path = resolve_prompt_path(config_path, config)
    template = outlines.Template.from_file(str(prompt_path))

    models_cfg = config.get("models", {})
    if not models_cfg:
        raise ValueError("Config missing 'models'")

    only_models = (
        None
        if not args.only_models
        else {p.strip() for p in args.only_models.split(",") if p.strip()}
    )
    if only_models is not None:
        unknown = only_models - set(models_cfg.keys())
        if unknown:
            raise ValueError(f"--only-models unknown aliases: {sorted(unknown)}")
        models = {k: v for k, v in models_cfg.items() if k in only_models}
        if not models:
            raise ValueError("--only-models filtered out all models")
    else:
        models = dict(models_cfg)

    base_sampling_cfg = dict(config.get("sampling_params") or {})
    model_params = config.get("model_params", {})
    model_overrides = config.get("model_params_overrides", {})
    sampling_overrides = config.get("sampling_params_overrides", {})

    logger.info("Prompt      : %s", prompt_path)
    logger.info("Models      : %s", ", ".join(models.keys()))

    input_path = args.input_jsonl.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSONL not found: {input_path}")

    for model_alias, model_path in models.items():
        logger.info("Loading model %s => %s", model_alias, model_path)

        batch_size = _resolve_model_batch_size(config, model_alias)
        logger.info("Batch size  : %d", batch_size)

        jsonl_path = args.jsonl_dir / f"{model_alias}.jsonl"
        jsonl_store = JsonlStore(
            path=jsonl_path,
            model_alias=model_alias,
            logger=logger,
        )

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        effective_params = dict(model_params)
        model_override = {
            k: v
            for k, v in (model_overrides.get(model_alias) or {}).items()
            if k not in _PIPELINE_ONLY_KEYS
        }
        effective_params.update(model_override)
        model_init_params = _with_rope_scaling_compat(
            model_path,
            effective_params,
            logger,
        )

        current_sampling_cfg = dict(base_sampling_cfg)
        sampling_override = sampling_overrides.get(model_alias) or {}
        current_sampling_cfg.update(sampling_override)
        model_sampling_params = SamplingParams(**current_sampling_cfg)

        try:
            llm = LLM(
                model=model_path,
                trust_remote_code=True,
                **model_init_params,
            )
        except AttributeError as exc:
            if "all_special_tokens_extended" not in str(exc):
                raise
            if str(model_init_params.get("tokenizer_mode", "")).lower() == "slow":
                raise
            retry_params = dict(model_init_params)
            retry_params["tokenizer_mode"] = "slow"
            logger.warning(
                "Tokenizer compatibility issue for %s; retrying with "
                "tokenizer_mode=slow",
                model_alias,
            )
            llm = LLM(
                model=model_path,
                trust_remote_code=True,
                **retry_params,
            )

        model = outlines.models.vllm_offline.VLLMOffline(llm)
        tokenizer = llm.get_tokenizer()

        try:
            run_model_on_input(
                input_path=input_path,
                template=template,
                model_alias=model_alias,
                model=model,
                tokenizer=tokenizer,
                base_sampling_cfg=base_sampling_cfg,
                sampling_params=model_sampling_params,
                batch_size=batch_size,
                retry_failed_rounds=args.retry_failed_rounds,
                jsonl_store=jsonl_store,
                logger=logger,
            )
        finally:
            del model
            del llm
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    logger.info("Annotation process completed.")


if __name__ == "__main__":
    main()
