"""
Run RAGAS Evaluation (Incremental) desde JSONL

- Lee un fichero JSONL con columnas:
    ["id", "user_input", "response", "reference", "retrieved_contexts", "reference_contexts"]
- Ejecuta evaluación RAGAS incrementalmente (chunk_size, max_concurrency, cache, retries)
- Exporta resultado final con columnas originales + métricas RAGAS

Uso:
    python run_ragas.py -c config.yaml
"""

import json
import hashlib
import math
import random
import time
import inspect
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import asyncio

import pandas as pd
import yaml
import argparse
from openai import AsyncOpenAI

from ragas.llms import llm_factory
from ragas.metrics.collections import (
    Faithfulness,
    AnswerRelevancy,
    FactualCorrectness,
    ContextPrecision,
    ContextUtilization,
    ContextRelevance,
)

try:
    from ragas.embeddings.base import embedding_factory
except ImportError:
    from ragas.embeddings import embedding_factory


# ── Mapa nombre → clase de métrica RAGAS ───────────────────
RAGAS_METRIC_MAP = {
    # Retrieval
    "context_precision": ContextPrecision,
    "context_utilization": ContextUtilization,
    "context_relevance": ContextRelevance,
    # Answer generation
    "faithfulness": Faithfulness,
    "answer_relevancy": AnswerRelevancy,
    "factual_correctness": FactualCorrectness,
}

RETRIEVAL_METRICS = [
    "context_precision",
    "context_utilization",
    "context_relevance",
]

GENERATION_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "factual_correctness",
]

# Kwargs que cada métrica espera en ascore()
RAGAS_METRIC_KWARGS = {
    # Retrieval
    "context_precision": ["user_input", "reference", "retrieved_contexts"],
    "context_utilization": ["user_input", "response", "retrieved_contexts"],
    "context_relevance": ["user_input", "retrieved_contexts"],
    # Answer generation
    "faithfulness": ["user_input", "response", "retrieved_contexts"],
    "answer_relevancy": ["user_input", "response"],
    "factual_correctness": ["response", "reference"],
}

# Lista por defecto (sin NonLLMContextPrecisionWithReference)
DEFAULT_RAGAS_METRICS = [
    "context_precision",
    "context_utilization",
    "context_relevance",
    "faithfulness",
    "answer_relevancy",
    "factual_correctness",
]

# Métricas adicionales (no RAGAS)
CUSTOM_RETRIEVAL_METRICS = [
    "hit@1",
    "hit@k",
]


# =========================
# UTILIDADES
# =========================


def load_config(path: str = "config.yaml") -> dict:
    """Carga la configuración desde un archivo YAML."""
    cfg_path = Path(__file__).parent / path
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _embedding_model_id_from_cfg(cfg: dict) -> str:
    """Obtiene el model_id de embeddings usando model_name.split('/')[-1]."""
    model_name = (
        cfg.get("encoder-api", {}).get("model_name")
        if isinstance(cfg, dict)
        else None
    )
    if not model_name:
        return "unknown-model"
    model_id = str(model_name).split("/")[-1].strip()
    return model_id or "unknown-model"


def _available_query_samples_for_domain(base_dir: Path, domain: str) -> list[int]:
    data_dir = base_dir / "data" / domain
    if not data_dir.exists():
        return []

    samples: set[int] = set()
    for p in data_dir.glob(f"ALIA-{domain}-triplets-*.jsonl"):
        m = re.search(r"-(\d+)\.jsonl$", p.name)
        if m:
            samples.add(int(m.group(1)))
    return sorted(samples)


def _available_context_samples_for_domain(base_dir: Path, domain: str) -> list[int]:
    data_dir = base_dir / "data" / domain
    if not data_dir.exists():
        return []

    samples: set[int] = set()
    for p in data_dir.glob(f"ALIA-{domain}-contexts-*.jsonl"):
        m = re.search(r"-(\d+)\.jsonl$", p.name)
        if m:
            samples.add(int(m.group(1)))
    return sorted(samples)


def _samples_help_epilog(base_dir: Path) -> str:
    domains = os.listdir(base_dir / "data") if (base_dir / "data").exists() else []
    lines = ["Muestras disponibles detectadas por dominio (además de 0=all):"]
    for d in domains:
        q_vals = _available_query_samples_for_domain(base_dir, d)
        c_vals = _available_context_samples_for_domain(base_dir, d)
        lines.append(
            f"- {d}: query(sampled)={q_vals if q_vals else []} | context(contexts)={c_vals if c_vals else []}"
        )
    return "\n".join(lines)


# =========================
# RAGAS HELPERS
# =========================


def create_ragas_llm(cfg: dict):
    """LLM evaluador para RAGAS via llm_factory (InstructorLLM, thinking deshabilitado)."""
    r = cfg["llm-api"]
    client = AsyncOpenAI(
        api_key=r["api_key"],
        base_url=r["base_url"],
        max_retries=0,
    )
    # Try to pass max_tokens directly; if factory doesn't accept it, pass via extra_body
    max_tokens = r.get("max_tokens")
    try:
        return llm_factory(
            r["model_name"],
            provider="openai",
            client=client,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    except TypeError:
        return llm_factory(
            r["model_name"],
            provider="openai",
            client=client,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": max_tokens,
            },
        )


def create_ragas_embeddings(cfg: dict):
    """Embeddings para RAGAS (necesario para answer_relevancy, etc.).
    Devuelve None si no hay config de embeddings."""
    emb = cfg["encoder-api"]
    if not emb or not emb.get("api_key") or not emb.get("model_name"):
        return None
    client = AsyncOpenAI(
        api_key=emb["api_key"],
        base_url=emb.get("base_url"),
        max_retries=0,
    )
    return embedding_factory("openai", model=emb["model_name"], client=client)


# --------------------------
# Cache & helpers for incremental sending / retries
# --------------------------


def _make_cache_key(metric_name: str, inp: dict) -> str:
    s = json.dumps(
        {"metric": metric_name, "inp": inp}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _load_cache(path: str) -> dict:
    if not path:
        return {}
    p = Path(path)
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: dict, path: str) -> None:
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _run_maybe_awaitable(value):
    """Run awaitables synchronously; return plain values unchanged."""
    if asyncio.iscoroutine(value):
        return asyncio.run(value)
    if inspect.isawaitable(value):
        async def _awaitable_adapter(awaitable_obj):
            return await awaitable_obj

        return asyncio.run(_awaitable_adapter(value))
    return value


def _call_with_retries(
    call_coro_fn, max_retries: int, backoff_base_s: float, inference_delay_s: float = 0.0
):
    """Call a callable with retries and exponential backoff (sync flow)."""
    last_exc = None
    for attempt in range(0, max_retries + 1):
        try:
            # Delay configurable before each API call to avoid rate limits
            if inference_delay_s and inference_delay_s > 0:
                time.sleep(float(inference_delay_s))
            return _run_maybe_awaitable(call_coro_fn())
        except Exception as e:
            last_exc = e
            if attempt >= max_retries:
                raise
            # backoff with jitter
            wait = backoff_base_s * (2**attempt) + random.random() * 0.5
            time.sleep(wait)
    if last_exc:
        raise last_exc


def _call_with_global_retry(
    call_fn,
    metric_name: str,
    sample_idx: int,
    total_samples: int,
    global_retries: int = 1,
    retry_wait_s: float = 10.0,
):
    """Call with a fixed number of global retries at sample level."""
    last_exc = None
    for attempt in range(0, global_retries + 1):
        try:
            return _run_maybe_awaitable(call_fn())
        except Exception as e:
            last_exc = e
            if attempt >= global_retries:
                raise

            wait_s = max(0.0, float(retry_wait_s or 0.0))
            logging.warning(
                "%s [%s/%s]: fallo en intento global %s/%s (%s). Reintentando en %.1fs.",
                metric_name,
                sample_idx + 1,
                total_samples,
                attempt + 1,
                global_retries + 1,
                e,
                wait_s,
            )
            if wait_s > 0:
                time.sleep(wait_s)

    if last_exc:
        raise last_exc


def _extract_score_reason(single_res) -> tuple[float, str]:
    """Normaliza score/reason desde el resultado devuelto por RAGAS."""
    if single_res is None:
        return float("nan"), "Error: empty response"

    val = getattr(single_res, "value", None)
    if val is not None:
        score = float(val)
    else:
        try:
            score = float(single_res)
        except Exception:
            score = float("nan")

    reason = getattr(single_res, "reason", None) or ""
    if (
        not reason
        and hasattr(single_res, "traces")
        and single_res.traces
    ):
        trace_parts = [f"{kk}: {vv}" for kk, vv in single_res.traces.items()]
        reason = " | ".join(trace_parts)

    return score, reason


def _call_metric_batch(metric, batch_inputs: list[dict]):
    """Ejecuta scoring por lote usando la API batch disponible de la métrica."""
    if hasattr(metric, "abatch_score"):
        return _run_maybe_awaitable(metric.abatch_score(batch_inputs))
    if hasattr(metric, "batch_score"):
        return _run_maybe_awaitable(metric.batch_score(batch_inputs))
    raise AttributeError(
        f"{metric.name}: la métrica no soporta batch scoring (abatch_score/batch_score)."
    )


# --------------------------
# Checkpoint / Backup helpers
# --------------------------


def _get_backup_path(
    backup_dir: str,
    model_id: str,
    domain: str,
    task: str,
    metric_name: str,
    sample_query: int,
    sample_context: int,
) -> Path:
    """Construye la ruta para el fichero de backup de una métrica."""
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)
    filename = (
        f"checkpoint-{model_id}-{domain}-{task}-{metric_name}-"
        f"q{sample_query}-c{sample_context}.json"
    )
    return backup_path / filename


def _save_checkpoint(
    backup_path: Path,
    scores: list,
    reasons: list,
    sample_count: int,
) -> None:
    """Guarda checkpoint con scores y reasons hasta el índice sample_count."""
    try:
        checkpoint_data = {
            "timestamp": datetime.now().isoformat(),
            "processed_count": sample_count,
            "scores": scores[:sample_count],
            "reasons": reasons[:sample_count],
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
        logging.debug(f"Checkpoint guardado: {backup_path} (muestras: {sample_count})")
    except Exception as e:
        logging.error(f"Error guardando checkpoint {backup_path}: {e}")


def _load_checkpoint(backup_path: Path) -> tuple[list, list, int] | None:
    """Carga checkpoint previo. Devuelve (scores, reasons, processed_count) o None si no existe."""
    if not backup_path.exists():
        return None
    try:
        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        scores = data.get("scores", [])
        reasons = data.get("reasons", [])
        processed_count = data.get("processed_count", len(scores))
        logging.info(
            f"Checkpoint cargado desde {backup_path}: {processed_count} muestras procesadas"
        )
        return scores, reasons, processed_count
    except Exception as e:
        logging.error(f"Error cargando checkpoint {backup_path}: {e}")
        return None


def _cleanup_backup(backup_path: Path) -> None:
    """Elimina fichero de backup al terminar la métrica."""
    if backup_path.exists():
        try:
            backup_path.unlink()
            logging.info(f"Backup eliminado: {backup_path}")
        except Exception as e:
            logging.error(f"Error eliminando backup {backup_path}: {e}")


# =========================
# RAGAS EVALUATION
# =========================



def _metrics_for_task(task: str) -> list[str]:
    if task == "hit":
        return CUSTOM_RETRIEVAL_METRICS
    if task == "retrieval":
        return RETRIEVAL_METRICS
    if task == "generation":
        return GENERATION_METRICS
    return RETRIEVAL_METRICS + GENERATION_METRICS


def check_existing_output(
    output_path: str,
    task: str,
) -> tuple[bool, List[str], List[str]]:
    """
    Verifica si el output ya existe y contiene todas las métricas necesarias.
    
    Devuelve (output_exists, computed_metrics, missing_metrics):
      - output_exists: True si el fichero existe
      - computed_metrics: Lista de métricas ya presentes en el output
      - missing_metrics: Lista de métricas requeridas que faltan
    """
    output_file = Path(output_path)
    
    if not output_file.exists():
        
        logging.info(f"Output no existe: {output_path}")
        # Comprobar que los ficheros individuales de las métricas tampoco estén
        exists, computed_metrics, missing_metrics = False, [], []
        for metric in _metrics_for_task(task):
            metric_file = output_file.parent / "by_metric" / f"{output_file.stem}-{metric}.csv"
            if metric_file.exists():
                logging.warning(f"Fichero de métrica individual encontrado sin output completo: {metric_file}")
                exists = True
                computed_metrics.append(metric)
            else:
                missing_metrics.append(metric)
        logging.info(f"Output completo no encontrado, pero métricas individuales detectadas: {computed_metrics}, faltan: {missing_metrics}")
        return exists, computed_metrics, missing_metrics
    
    try:
        # Cargar el CSV para verificar columnas
        df = pd.read_csv(output_path)
        logging.info(f"CSV de output cargado: {len(df)} filas, columnas: {list(df.columns)}")
        
        required_metrics = _metrics_for_task(task)
        logging.info(f"Task: {task}, métricas requeridas: {required_metrics}")
        
        # Comprobar qué métricas ya están en el output
        computed = []
        missing = []
        for metric in required_metrics:
            if metric in df.columns:
                # Verificar que hay valores válidos (no solo NaN)
                valid_count = df[metric].notna().sum()
                if valid_count > 0:
                    computed.append(metric)
                    logging.info(f"  {metric}: PRESENTE ({valid_count}/{len(df)} valores válidos)")
                else:
                    missing.append(metric)
                    logging.info(f"  {metric}: AUSENTE (sólo NaN)")
            else:
                missing.append(metric)
                logging.info(f"  {metric}: AUSENTE (no en columnas)")
        
        return True, computed, missing
    
    except Exception as e:
        logging.error(f"Error al verificar output: {e}")
        return False, [], []


def _has_required_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _find_invalid_samples_for_metric(samples: List[dict], metric_name: str) -> list[tuple[int, list[str]]]:
    required_keys = RAGAS_METRIC_KWARGS.get(metric_name, [])
    invalid_samples: list[tuple[int, list[str]]] = []

    for idx, sample in enumerate(samples, start=1):
        missing_fields = []
        for key in required_keys:
            if key not in sample or not _has_required_value(sample.get(key)):
                missing_fields.append(key)
        if missing_fields:
            invalid_samples.append((idx, missing_fields))

    return invalid_samples


def build_ragas_metrics(cfg: dict, task: str, ragas_llm=None, ragas_emb=None) -> list:
    """Instancia las métricas RAGAS (collections) indicadas en config.yaml."""
    task_metrics = _metrics_for_task(task)
    config_metrics = cfg.get("ragas", {}).get("metrics") or DEFAULT_RAGAS_METRICS
    requested_metrics = [m for m in task_metrics if m in config_metrics]
    if not requested_metrics:
        requested_metrics = task_metrics

    metrics = []
    failed_metrics = []
    for name in requested_metrics:
        cls = RAGAS_METRIC_MAP.get(name)
        if cls is None:
            print(f"  Warning: métrica RAGAS desconocida '{name}', se omite.")
            continue
        for kwargs in [
            {"llm": ragas_llm, "embeddings": ragas_emb},
            {"llm": ragas_llm},
            {"embeddings": ragas_emb},
            {},
        ]:
            filtered = {k: v for k, v in kwargs.items() if v is not None}
            try:
                metrics.append(cls(**filtered))
                break
            except Exception:
                continue
        else:
            print(f"  Warning: no se pudo instanciar la métrica '{name}', se omite.")
            failed_metrics.append(name)

    if failed_metrics:
        raise ValueError(
            "No se pudieron instanciar las métricas requeridas: "
            f"{failed_metrics}."
        )

    if not metrics:
        raise ValueError("No se configuraron métricas RAGAS válidas en config.yaml")
    return metrics


def _score_with_reason(metric, inp: dict) -> tuple[float, str]:
    """
    Ejecuta ascore para una métrica y construye un reason a partir de los pasos internos.
    """
    m_name = metric.name
    try:
        if m_name == "faithfulness":
            user_input = inp["user_input"]
            response = inp["response"]
            contexts = inp["retrieved_contexts"]
            statements = _run_maybe_awaitable(
                metric._create_statements(user_input, response)
            )
            if not statements:
                return float("nan"), "No statements generated"
            context_str = "\n".join(contexts)
            verdicts = _run_maybe_awaitable(
                metric._create_verdicts(statements, context_str)
            )
            score = metric._compute_score(verdicts)
            reason_parts = []
            if hasattr(verdicts, "statements"):
                for v in verdicts.statements:
                    stmt = getattr(v, "statement", str(v))
                    verdict = getattr(v, "verdict", "")
                    reason_text = getattr(v, "reason", "")
                    reason_parts.append(f"[{verdict}] {stmt}: {reason_text}")
            else:
                reason_parts.append(str(verdicts))
            return float(score), " || ".join(reason_parts) if reason_parts else ""
        else:
            result = _run_maybe_awaitable(metric.ascore(**inp))
            val = result.value if hasattr(result, "value") else float(result)
            reason = getattr(result, "reason", None) or ""
            return val, reason
    except Exception as e:
        return float("nan"), f"Error: {e}"


def run_ragas_evaluation(
    samples_data: List[dict],
    cfg: dict,
    task: str,
    per_metric_output_dir: str | None = None,
    per_metric_output_prefix: str = "ragas",
    domain: str = "unknown",
    sample_query: int = 0,
    sample_context: int = 0,
    skip_metrics: List[str] | None = None,
    force: bool = False,
) -> tuple[pd.DataFrame, list, list[str]]:
    """
    Ejecuta la evaluación RAGAS usando scoring individual por métrica.
    Devuelve (DataFrame con scores/reasons, lista de nombres de métrica).
    
    Args:
        skip_metrics: Lista de nombres de métricas a saltarse (ya computadas).
        force: Si True, ignora skip_metrics y ejecuta todas las métricas.
    """
    if skip_metrics is None:
        skip_metrics = []
    
    logging.info(f"=== Iniciando run_ragas_evaluation ===")
    logging.info(f"Domain: {domain}, Task: {task}, Samples: {len(samples_data)}, Sample-Query: {sample_query}, Sample-Context: {sample_context}")
    if skip_metrics and not force:
        logging.info(f"Métricas a saltarse (ya computadas): {skip_metrics}")

    run_ragas_metrics = task in ("retrieval", "generation", "all")
    if run_ragas_metrics:
        ragas_llm = create_ragas_llm(cfg)
        ragas_emb = create_ragas_embeddings(cfg)
        metrics = build_ragas_metrics(cfg, task=task, ragas_llm=ragas_llm, ragas_emb=ragas_emb)
    else:
        metrics = []
        logging.info(
            "Task '%s': se evaluarán solo métricas custom (%s)",
            task,
            ", ".join(CUSTOM_RETRIEVAL_METRICS),
        )

    logging.info(f"Métricas RAGAS configuradas: {len(metrics)}")
    for m in metrics:
        logging.info(f"  - {m.__class__.__name__}")

    # Preparar inputs para cada sample
    full_inputs = []
    for s in samples_data:
        retrieved_contexts = s.get("retrieved_contexts")
        if retrieved_contexts is None:
            retrieved_contexts = []
        elif not isinstance(retrieved_contexts, list):
            retrieved_contexts = [str(retrieved_contexts)] if str(retrieved_contexts) else []

        reference_contexts = s.get("reference_contexts")
        if reference_contexts is None:
            reference_contexts = []
        elif not isinstance(reference_contexts, list):
            reference_contexts = [str(reference_contexts)] if str(reference_contexts) else []

        full_inputs.append(
            {
                "user_input": s.get("user_input", ""),
                "response": s.get("response", ""),
                "retrieved_contexts": retrieved_contexts,
                "reference": s.get("reference", ""),
                "reference_contexts": reference_contexts,
            }
        )

    # RAGAS sending controls from config
    ragas_cfg = cfg.get("ragas", {})
    send_incrementally = bool(ragas_cfg.get("send_incrementally", True))
    sample_fraction = float(ragas_cfg.get("sample_fraction", 1.0) or 1.0)
    chunk_size = int(ragas_cfg.get("chunk_size", 10) or 10)
    ragas_delay_s = float(ragas_cfg.get("inference_delay_s", 0.0) or 0.0)
    llm_delay_s = float(cfg.get("llm-api", {}).get("inference_delay_s", 0.0) or 0.0)
    inference_delay_s = max(1.0, ragas_delay_s, llm_delay_s)
    if ragas_delay_s != llm_delay_s:
        logging.info(
            "Delay efectivo = max(ragas=%ss, llm-api=%ss) -> %ss",
            ragas_delay_s,
            llm_delay_s,
            inference_delay_s,
        )
    # Interpret max_calls explicitly: 0 = unlimited, None -> default 30
    _raw_max_calls = ragas_cfg.get("max_calls", None)
    if _raw_max_calls is None:
        max_calls = 30
    else:
        try:
            max_calls = int(_raw_max_calls)
        except Exception:
            max_calls = 30

    max_retries = int(ragas_cfg.get("max_retries", 3) or 3)
    backoff_base_s = float(ragas_cfg.get("backoff_base_s", 2) or 2.0)
    cache_path = ragas_cfg.get("cache_path") or ""
    # Reintento global por muestra al llegar a except (se aplica una sola vez)
    global_retries = 1
    global_retry_wait_s = float(ragas_cfg.get("global_retry_wait_s", 10.0) or 10.0)
    
    # Backup configuration
    backup_batch_size = int(ragas_cfg.get("backup_batch_size", 100) or 100)
    backup_dir = ragas_cfg.get("backup_dir", ".ragas_backups") or ".ragas_backups"
    model_id = _embedding_model_id_from_cfg(cfg)

    max_concurrency = int(ragas_cfg.get("max_concurrency", 2) or 2)
    if max_concurrency != 1:
        logging.info(
            "Modo síncrono activo: `max_concurrency=%s` no aplica y se ignora.",
            max_concurrency,
        )

    # Load cache
    cache = _load_cache(cache_path) if cache_path else {}

    n_samples = len(samples_data)
    if n_samples == 0:
        return pd.DataFrame(), [m.name for m in metrics], []

    # Decide sampling if estimated calls exceed max_calls
    if send_incrementally and max_calls > 0:
        est_calls_per_metric = []
        for m in metrics:
            # Endurecido: scoring por muestra para evitar ráfagas internas
            est_calls_per_metric.append(n_samples)
        total_est = sum(est_calls_per_metric)
        if total_est > max_calls:
            avg_calls_per_sample = total_est / n_samples
            allowed_samples = max(1, int(max_calls / max(1, avg_calls_per_sample)))
            sample_fraction = min(sample_fraction, allowed_samples / n_samples)

    include_retrieval_custom = task in ("retrieval", "all", "hit")

    # Para cada métrica: ejecutar scoring con chunking, cache, retries
    metric_names: List[str] = []
    all_scores: Dict[str, List] = {}
    all_reasons: Dict[str, List] = {}
    per_metric_files: List[str] = []

    # Métricas custom de retrieval (sin API):
    # - hit@1: acierto exacto en top-1
    # - hit@k: acierto si la referencia aparece en cualquier posición del top-k recuperado
    if include_retrieval_custom:
        p1_scores: List[float] = []
        p1_reasons: List[str] = []
        pk_scores: List[float] = []
        pk_reasons: List[str] = []

        logging.info(f"Iniciando evaluación de hit@1/hit@k ({len(samples_data)} muestras)")

        # Verificar si hay checkpoint previo
        backup_path = _get_backup_path(
            backup_dir,
            model_id,
            domain,
            task,
            "hit@1",
            sample_query,
            sample_context,
        )
        checkpoint = _load_checkpoint(backup_path)
        if checkpoint:
            p1_scores, p1_reasons, start_idx = checkpoint
            logging.info(f"hit@1: recuperado desde checkpoint, reanudando desde muestra {start_idx}")

            # Reconstruir hit@k para la parte ya procesada
            for prev_idx in range(start_idx):
                prev_sample = samples_data[prev_idx]
                prev_id_passage = prev_sample.get("id_passage") or prev_sample.get("id_reference_context")
                prev_retrieved_ids = prev_sample.get("id_retrieved_contexts")
                if not prev_retrieved_ids:
                    prev_single_top1 = prev_sample.get("id_retrieved_context")
                    prev_retrieved_ids = [prev_single_top1] if prev_single_top1 else []

                if isinstance(prev_retrieved_ids, list):
                    prev_retrieved_ids_str = [
                        str(x) for x in prev_retrieved_ids if x is not None and str(x) != ""
                    ]
                elif prev_retrieved_ids is None:
                    prev_retrieved_ids_str = []
                else:
                    prev_retrieved_ids_str = [str(prev_retrieved_ids)] if str(prev_retrieved_ids) else []

                if prev_id_passage is None:
                    pk_scores.append(float("nan"))
                    pk_reasons.append("Missing id_passage/id_reference_context")
                else:
                    prev_in_top_k = str(prev_id_passage) in prev_retrieved_ids_str
                    pk_scores.append(1.0 if prev_in_top_k else 0.0)
                    pk_reasons.append(
                        f"id_passage={prev_id_passage} in_top_k={prev_in_top_k} top_k={prev_retrieved_ids_str}"
                    )
        else:
            start_idx = 0
            logging.info(f"hit@1: sin checkpoint previo, comenzando desde muestra 0")

        for idx, s in enumerate(samples_data):
            # Si ya fue procesado en checkpoint previo, saltar
            if idx < start_idx:
                continue

            id_passage = s.get("id_passage") or s.get("id_reference_context")
            retrieved_ids = s.get("id_retrieved_contexts")
            if not retrieved_ids:
                single_top1 = s.get("id_retrieved_context")
                retrieved_ids = [single_top1] if single_top1 else []

            if isinstance(retrieved_ids, list):
                top1 = str(retrieved_ids[0]) if len(retrieved_ids) > 0 else ""
                retrieved_ids_str = [
                    str(x) for x in retrieved_ids if x is not None and str(x) != ""
                ]
            elif retrieved_ids is None:
                top1 = ""
                retrieved_ids_str = []
            else:
                top1 = str(retrieved_ids)
                retrieved_ids_str = [top1] if top1 else []

            if id_passage is None:
                p1_scores.append(float("nan"))
                p1_reasons.append("Missing id_passage/id_reference_context")
                pk_scores.append(float("nan"))
                pk_reasons.append("Missing id_passage/id_reference_context")
                logging.debug(f"hit@1 [{idx+1}/{len(samples_data)}] (id={s.get('id')}): NaN (missing id_passage)")
                logging.debug(f"hit@k [{idx+1}/{len(samples_data)}] (id={s.get('id')}): NaN (missing id_passage)")
            else:
                exact = 1.0 if str(id_passage) == top1 else 0.0
                p1_scores.append(exact)
                p1_reasons.append(f"id_passage={id_passage} top1={top1}")
                match_str = "✓" if exact == 1.0 else "✗"
                logging.debug(f"hit@1 [{idx+1}/{len(samples_data)}] (id={s.get('id')}): {match_str} score={exact} (ref={id_passage}, top1={top1})")

                in_top_k = str(id_passage) in retrieved_ids_str
                pk = 1.0 if in_top_k else 0.0
                pk_scores.append(pk)
                pk_reasons.append(
                    f"id_passage={id_passage} in_top_k={in_top_k} top_k={retrieved_ids_str}"
                )
                logging.debug(
                    f"hit@k [{idx+1}/{len(samples_data)}] (id={s.get('id')}): {'✓' if pk == 1.0 else '✗'} "
                    f"score={pk} (ref={id_passage}, top_k={retrieved_ids_str})"
                )

            # Guardar checkpoint cada backup_batch_size muestras
            if (idx + 1) % backup_batch_size == 0:
                _save_checkpoint(backup_path, p1_scores, p1_reasons, len(p1_scores))
                logging.info(f"hit@1: checkpoint guardado ({idx + 1}/{len(samples_data)} muestras procesadas)")

        all_scores["hit@1"] = p1_scores
        all_reasons["hit@1_reason"] = p1_reasons
        metric_names.append("hit@1")

        all_scores["hit@k"] = pk_scores
        all_reasons["hit@k_reason"] = pk_reasons
        metric_names.append("hit@k")

        # Limpiar backup al terminar métrica
        _cleanup_backup(backup_path)
        logging.info(f"hit@1/hit@k: evaluación completada ({len(p1_scores)} muestras)")

        if per_metric_output_dir:
            per_metric_path = export_ragas_metric_output(
                samples_data=samples_data,
                metric_name="hit@1",
                scores=p1_scores,
                reasons=p1_reasons,
                output_dir=per_metric_output_dir,
                output_prefix=per_metric_output_prefix,
            )
            per_metric_files.append(per_metric_path)
            per_metric_path = export_ragas_metric_output(
                samples_data=samples_data,
                metric_name="hit@k",
                scores=pk_scores,
                reasons=pk_reasons,
                output_dir=per_metric_output_dir,
                output_prefix=per_metric_output_prefix,
            )
            per_metric_files.append(per_metric_path)
   
    for metric in metrics:
        m_name = metric.name
        
        # Verificar si esta métrica debe saltarse
        if m_name in skip_metrics and not force:
            logging.info(f"{m_name}: SALTANDO (ya computada y force=False)")
            metric_names.append(m_name)
            # Rellenar con NaN para mantener estructura consistente
            all_scores[m_name] = [float("nan")] * len(full_inputs)
            all_reasons[f"{m_name}_reason"] = [""] * len(full_inputs)
            continue
        
        expected_keys = RAGAS_METRIC_KWARGS.get(m_name)

        invalid_samples = _find_invalid_samples_for_metric(full_inputs, m_name)
        if invalid_samples:
            preview = ", ".join(
                f"#{sample_idx} missing {fields}"
                for sample_idx, fields in invalid_samples[:5]
            )
            if len(invalid_samples) > 5:
                preview += f" ... (+{len(invalid_samples) - 5} more)"
            warning_msg = (
                f"{m_name}: se omite porque hay muestras con campos requeridos vacíos o ausentes: "
                f"{preview}"
            )
            print(f"Warning: {warning_msg}")
            logging.warning(warning_msg)
            continue

        metric_names.append(m_name)

        if expected_keys is None:
            import inspect

            sig = inspect.signature(metric.ascore)
            expected_keys = [p for p in sig.parameters if p != "self"]

        batch_inputs = [
            {k: inp[k] for k in expected_keys if k in inp} for inp in full_inputs
        ]

        if force and m_name in skip_metrics:
            logging.info(f"  RE-EVALUANDO {m_name} due to --force ({len(batch_inputs)} samples)...")
            print(f"  RE-EVALUANDO {m_name} (force=true, {len(batch_inputs)} samples)...")
        else:
            print(f"  Evaluando {m_name} ({len(batch_inputs)} samples)...")
            logging.info(f"Iniciando métrica: {m_name} ({len(batch_inputs)} muestras)")

        scores = [float("nan")] * len(batch_inputs)
        reasons = [""] * len(batch_inputs)
        
        # Verificar si hay checkpoint previo
        backup_path = _get_backup_path(
            backup_dir,
            model_id,
            domain,
            task,
            m_name,
            sample_query,
            sample_context,
        )
        checkpoint = _load_checkpoint(backup_path)
        if checkpoint:
            prev_scores, prev_reasons, start_idx = checkpoint
            # Restaurar scores y reasons previos
            scores[:start_idx] = prev_scores[:start_idx]
            reasons[:start_idx] = prev_reasons[:start_idx]
            logging.info(f"{m_name}: reanudando desde muestra {start_idx}/{len(batch_inputs)}")
        else:
            start_idx = 0
            logging.debug(f"{m_name}: comenzando desde muestra 0")

        if m_name == "faithfulness":
            # process per-sample
            def score_single(i, inp):
                key = _make_cache_key(m_name, inp)
                if key in cache:
                    cached = cache[key]
                    scores[i] = float(cached.get("score", float("nan")))
                    reasons[i] = cached.get("reason", "")
                    logging.debug(f"{m_name} [{i+1}/{len(full_inputs)}]: CACHE hit, score={scores[i]:.4f}")
                    return
                try:
                    res = _call_with_global_retry(
                        lambda: _call_with_retries(
                            lambda: _score_with_reason(metric, inp),
                            max_retries,
                            backoff_base_s,
                            inference_delay_s=inference_delay_s,
                        ),
                        metric_name=m_name,
                        sample_idx=i,
                        total_samples=len(full_inputs),
                        global_retries=global_retries,
                        retry_wait_s=global_retry_wait_s,
                    )
                    if res is None:
                        scores[i] = float("nan")
                        reasons[i] = "Error: empty response"
                        logging.warning(f"{m_name} [{i+1}/{len(full_inputs)}]: NaN (empty response)")
                        return
                    sc, rs = res
                    scores[i] = float(sc) if sc is not None else float("nan")
                    reasons[i] = rs or ""
                    if cache is not None:
                        cache[key] = {"score": scores[i], "reason": reasons[i]}
                    logging.debug(f"{m_name} [{i+1}/{len(full_inputs)}]: score={scores[i]:.4f}")
                except Exception as e:
                    scores[i] = float("nan")
                    reasons[i] = f"Error: {e}"
                    logging.error(f"{m_name} [{i+1}/{len(full_inputs)}]: Error - {e}")

            for i, inp in enumerate(full_inputs):
                # Saltar si ya fue procesado en checkpoint
                if i < start_idx:
                    continue
                logging.debug(f"{m_name}: procesando muestra {i+1}/{len(full_inputs)}")
                score_single(i, inp)
                
                # Guardar checkpoint cada backup_batch_size muestras
                if (i + 1) % backup_batch_size == 0:
                    _save_checkpoint(backup_path, scores, reasons, i + 1)
                    logging.info(f"{m_name}: checkpoint guardado ({i + 1}/{len(batch_inputs)} muestras procesadas)")
        else:
            if send_incrementally:
                effective_chunk_size = max(1, int(chunk_size))
                logging.info(
                    "%s: modo batch incremental activo (chunk_size=%s)",
                    m_name,
                    effective_chunk_size,
                )

                for chunk_start in range(start_idx, len(batch_inputs), effective_chunk_size):
                    chunk_end = min(chunk_start + effective_chunk_size, len(batch_inputs))
                    chunk_indices = list(range(chunk_start, chunk_end))

                    pending_indices: List[int] = []
                    pending_inputs: List[dict] = []

                    for i in chunk_indices:
                        inp = batch_inputs[i]
                        logging.debug(f"{m_name}: procesando muestra {i+1}/{len(batch_inputs)}")

                        key = _make_cache_key(m_name, inp)
                        if key in cache:
                            cached = cache[key]
                            scores[i] = float(cached.get("score", float("nan")))
                            reasons[i] = cached.get("reason", "")
                            logging.debug(f"{m_name} [{i+1}/{len(batch_inputs)}]: CACHE hit, score={scores[i]:.4f}")
                            continue

                        pending_indices.append(i)
                        pending_inputs.append(inp)

                    if pending_inputs:
                        try:
                            batch_res = _call_with_retries(
                                lambda: _call_metric_batch(metric, pending_inputs),
                                max_retries,
                                backoff_base_s,
                                inference_delay_s=inference_delay_s,
                            )

                            if batch_res is None:
                                raise ValueError("Empty batch response")

                            if isinstance(batch_res, tuple):
                                batch_res = list(batch_res)
                            elif not isinstance(batch_res, list):
                                try:
                                    batch_res = list(batch_res)
                                except Exception as e:
                                    raise TypeError(
                                        f"Respuesta batch no iterable de tipo {type(batch_res)}"
                                    ) from e

                            if len(batch_res) != len(pending_inputs):
                                raise ValueError(
                                    f"Batch response size mismatch: esperado={len(pending_inputs)} recibido={len(batch_res)}"
                                )

                            for i, single_res in zip(pending_indices, batch_res):
                                scores[i], reasons[i] = _extract_score_reason(single_res)
                                key = _make_cache_key(m_name, batch_inputs[i])
                                if cache is not None:
                                    cache[key] = {"score": scores[i], "reason": reasons[i]}
                                if single_res is None:
                                    logging.warning(f"{m_name} [{i+1}/{len(batch_inputs)}]: NaN (empty response)")
                                else:
                                    logging.debug(f"{m_name} [{i+1}/{len(batch_inputs)}]: score={scores[i]:.4f}")

                        except Exception as batch_e:
                            logging.warning(
                                "%s [%s-%s/%s]: batch fallido (%s). Fallback por muestra.",
                                m_name,
                                chunk_start + 1,
                                chunk_end,
                                len(batch_inputs),
                                batch_e,
                            )
                            for i, inp in zip(pending_indices, pending_inputs):
                                try:
                                    single_res = _call_with_global_retry(
                                        lambda inp=inp: _call_with_retries(
                                            lambda: metric.ascore(**inp),
                                            max_retries,
                                            backoff_base_s,
                                            inference_delay_s=inference_delay_s,
                                        ),
                                        metric_name=m_name,
                                        sample_idx=i,
                                        total_samples=len(batch_inputs),
                                        global_retries=global_retries,
                                        retry_wait_s=global_retry_wait_s,
                                    )
                                    scores[i], reasons[i] = _extract_score_reason(single_res)

                                    key = _make_cache_key(m_name, inp)
                                    if cache is not None:
                                        cache[key] = {"score": scores[i], "reason": reasons[i]}

                                    if single_res is None:
                                        logging.warning(f"{m_name} [{i+1}/{len(batch_inputs)}]: NaN (empty response)")
                                    else:
                                        logging.debug(f"{m_name} [{i+1}/{len(batch_inputs)}]: score={scores[i]:.4f}")
                                except Exception as e:
                                    scores[i] = float("nan")
                                    reasons[i] = f"Error: {e}"
                                    logging.error(f"{m_name} [{i+1}/{len(batch_inputs)}]: Error - {e}")

                    for i in chunk_indices:
                        # Guardar checkpoint cada backup_batch_size muestras
                        if (i + 1) % backup_batch_size == 0:
                            _save_checkpoint(backup_path, scores, reasons, i + 1)
                            logging.info(
                                f"{m_name}: checkpoint guardado ({i + 1}/{len(batch_inputs)} muestras procesadas)"
                            )
            else:
                # send_incrementally desactivado: evaluación clásica por muestra
                for i, inp in enumerate(batch_inputs):
                    # Saltar si ya fue procesado en checkpoint
                    if i < start_idx:
                        continue

                    logging.debug(f"{m_name}: procesando muestra {i+1}/{len(batch_inputs)}")

                    key = _make_cache_key(m_name, inp)
                    if key in cache:
                        cached = cache[key]
                        scores[i] = float(cached.get("score", float("nan")))
                        reasons[i] = cached.get("reason", "")
                        logging.debug(f"{m_name} [{i+1}/{len(batch_inputs)}]: CACHE hit, score={scores[i]:.4f}")
                        continue

                    try:
                        single_res = _call_with_global_retry(
                            lambda: _call_with_retries(
                                lambda: metric.ascore(**inp),
                                max_retries,
                                backoff_base_s,
                                inference_delay_s=inference_delay_s,
                            ),
                            metric_name=m_name,
                            sample_idx=i,
                            total_samples=len(batch_inputs),
                            global_retries=global_retries,
                            retry_wait_s=global_retry_wait_s,
                        )

                        scores[i], reasons[i] = _extract_score_reason(single_res)

                        if cache is not None:
                            cache[key] = {"score": scores[i], "reason": reasons[i]}

                        if single_res is None:
                            logging.warning(f"{m_name} [{i+1}/{len(batch_inputs)}]: NaN (empty response)")
                        else:
                            logging.debug(f"{m_name} [{i+1}/{len(batch_inputs)}]: score={scores[i]:.4f}")
                    except Exception as e:
                        scores[i] = float("nan")
                        reasons[i] = f"Error: {e}"
                        logging.error(f"{m_name} [{i+1}/{len(batch_inputs)}]: Error - {e}")

                    # Guardar checkpoint cada backup_batch_size muestras
                    if (i + 1) % backup_batch_size == 0:
                        _save_checkpoint(backup_path, scores, reasons, i + 1)
                        logging.info(f"{m_name}: checkpoint guardado ({i + 1}/{len(batch_inputs)} muestras procesadas)")

        all_scores[m_name] = scores
        all_reasons[f"{m_name}_reason"] = reasons
        
        # Limpiar backup al terminar métrica
        _cleanup_backup(backup_path)
        
        # Estadísticas finales de la métrica
        valid_scores = [s for s in scores if not math.isnan(s)]
        if valid_scores:
            logging.info(f"{m_name}: completada - min={min(valid_scores):.4f}, max={max(valid_scores):.4f}, mean={sum(valid_scores)/len(valid_scores):.4f}, válidas={len(valid_scores)}/{len(scores)}")
        else:
            logging.warning(f"{m_name}: completada - sin scores válidos ({len(scores)} muestras con NaN)")

        if per_metric_output_dir:
            per_metric_path = export_ragas_metric_output(
                samples_data=samples_data,
                metric_name=m_name,
                scores=scores,
                reasons=reasons,
                output_dir=per_metric_output_dir,
                output_prefix=per_metric_output_prefix,
            )
            per_metric_files.append(per_metric_path)

    # Save cache
    if cache_path:
        try:
            _save_cache(cache, cache_path)
        except Exception:
            pass

    # Construir DataFrame
    df = pd.DataFrame(
        {
            "id": [s.get("id", "") for s in samples_data],
            "user_input": [s.get("user_input", "") for s in samples_data],
            "response": [s.get("response", "") for s in samples_data],
            "reference": [s.get("reference", "") for s in samples_data],
            "retrieved_contexts": [s.get("retrieved_contexts", []) for s in samples_data],
            "reference_contexts": [s.get("reference_contexts", []) for s in samples_data],
            **all_scores,
            **all_reasons,
        }
    )
    logging.info(f"=== Completada run_ragas_evaluation ===")
    logging.info(f"DataFrame construido: {len(df)} muestras, {len(metric_names)} métricas")
    return df, metric_names, per_metric_files


def extract_samples_from_jsonl(jsonl_path: str) -> List[dict]:
    """
    Lee un JSONL y extrae muestras para RAGAS.
    Columnas requeridas por fila:
    ["id", "user_input", "response", "reference", "retrieved_contexts", "reference_contexts"]
    Columnas opcionales (para hit@1):
    ["id_passage", "id_retrieved_contexts", "id_reference_context", "id_retrieved_context"]
    """
    logging.info(f"Extrayendo muestras desde: {jsonl_path}")
    
    required = {
        "id",
        "user_input",
        "response",
        "reference",
        "retrieved_contexts",
        "reference_contexts",
    }

    p = Path(jsonl_path)
    if not p.exists():
        raise ValueError(f"JSONL no encontrado: {jsonl_path}")

    samples: List[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as e:
                logging.error(f"Línea {line_no} inválida en JSONL: {e}")
                raise ValueError(f"Línea {line_no} inválida en JSONL: {e}") from e

            missing = [k for k in required if k not in row]
            if missing:
                raise ValueError(
                    f"Línea {line_no}: faltan columnas requeridas: {missing}"
                )

            retrieved_contexts = row.get("retrieved_contexts")
            if retrieved_contexts is None:
                retrieved_contexts = []
            elif not isinstance(retrieved_contexts, list):
                retrieved_contexts = [str(retrieved_contexts)]

            reference_contexts = row.get("reference_contexts")
            if reference_contexts is None:
                reference_contexts = []
            elif not isinstance(reference_contexts, list):
                reference_contexts = [str(reference_contexts)]

            id_retrieved_contexts = row.get("id_retrieved_contexts")
            if id_retrieved_contexts is None:
                id_retrieved_context = row.get("id_retrieved_context")
                id_retrieved_contexts = [str(id_retrieved_context)] if id_retrieved_context else []
            elif not isinstance(id_retrieved_contexts, list):
                id_retrieved_contexts = [str(id_retrieved_contexts)]

            id_passage = row.get("id_passage")
            if id_passage is None:
                id_passage = row.get("id_reference_context")

            samples.append(
                {
                    "id": row.get("id", ""),
                    "user_input": row.get("user_input", ""),
                    "response": row.get("response", ""),
                    "reference": row.get("reference", ""),
                    "retrieved_contexts": retrieved_contexts,
                    "reference_contexts": reference_contexts,
                    "id_passage": id_passage,
                    "id_retrieved_contexts": id_retrieved_contexts,
                    "id_reference_context": row.get("id_reference_context"),
                    "id_retrieved_context": row.get("id_retrieved_context"),
                }
            )
            
            if line_no % 100 == 0:
                logging.debug(f"Extractadas {line_no} líneas del JSONL...")

    logging.info(f"Extracted {len(samples)} samples from {jsonl_path} for RAGAS processing")
    return samples


def export_ragas_metric_output(
    samples_data: List[dict],
    metric_name: str,
    scores: List,
    reasons: List,
    output_dir: str,
    output_prefix: str,
) -> str:
    """Exporta resultados de una métrica concreta a un fichero independiente."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{output_prefix}-{metric_name}.csv"

    metric_df = pd.DataFrame(
        {
            "id": [s.get("id", "") for s in samples_data],
            "user_input": [s.get("user_input", "") for s in samples_data],
            "response": [s.get("response", "") for s in samples_data],
            "reference": [s.get("reference", "") for s in samples_data],
            "retrieved_contexts": [
                s.get("retrieved_contexts", []) for s in samples_data
            ],
            "reference_contexts": [
                s.get("reference_contexts", []) for s in samples_data
            ],
            metric_name: scores,
            f"{metric_name}_reason": reasons,
        }
    )
    metric_df.drop(f"{metric_name}_reason", axis=1).to_csv(out_path, index=False)
    metric_df.drop(["response", "reference", "retrieved_contexts", "reference_contexts", f"{metric_name}_reason"], axis=1).to_csv(out_path.as_posix().replace(".csv", "_scores.csv"), index=False)
    logging.info("Resultado por métrica guardado: %s", out_path)
    return str(out_path)


def export_ragas_output(
    ragas_df: pd.DataFrame,
    output_file: str,
) -> str:
    """
    Exporta resultados con prefijo ragas_ para métricas/reasons.
    Soporta salida CSV o JSONL según extensión de output_file.
    """
    base_cols = {
        "id",
        "user_input",
        "response",
        "reference",
        "retrieved_contexts",
        "reference_contexts"
    }

    out_df = ragas_df.copy()
    rename_map = {
        c: f"ragas_{c}"
        for c in out_df.columns
        if c not in base_cols
    }
    out_df = out_df.rename(columns=rename_map)

    out_parent = Path(output_file).parent
    if str(out_parent) and not out_parent.exists():
        out_parent.mkdir(parents=True, exist_ok=True)

    suffix = Path(output_file).suffix.lower()
    if suffix == ".jsonl":
        with open(output_file, "w", encoding="utf-8") as f:
            for record in out_df.to_dict(orient="records"):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        out_df.to_csv(output_file, index=False)

    print(f"Successfully exported {len(out_df)} rows to {output_file}")
    return output_file


def export_ragas_summary(
    ragas_df: pd.DataFrame,
    metric_names: List[str],
    output_file: str,
) -> str:
    """Exporta resumen por métrica con estadísticas agregadas."""
    rows = []
    for metric in metric_names:
        if metric not in ragas_df.columns:
            continue
        vals = pd.to_numeric(ragas_df[metric], errors="coerce").dropna()
        if len(vals) == 0:
            rows.append(
                {
                    "metric": metric,
                    "score_minimo": float("nan"),
                    "score_maximo": float("nan"),
                    "score_mean": float("nan"),
                    "score_median": float("nan"),
                    "score_std": float("nan"),
                }
            )
            continue

        rows.append(
            {
                "metric": metric,
                "score_minimo": float(vals.min()),
                "score_maximo": float(vals.max()),
                "score_mean": float(vals.mean()),
                "score_median": float(vals.median()),
                "score_std": float(vals.std(ddof=0)),
            }
        )

    summary_df = pd.DataFrame(rows)
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_path, index=False)
    logging.info("Resumen por métricas guardado: %s", out_path)
    return str(out_path)


# =========================
# MAIN
# =========================


def main(
    domain: str,
    task: str,
    config_path: str,
    input_jsonl: str,
    output_file: str,
    sample_query: int = 0,
    sample_context: int = 0,
    skip_metrics: List[str] | None = None,
    force: bool = False,
) -> None:
    """
    Lee un JSONL de evaluación, ejecuta RAGAS incremental, y exporta resultado final.
    
    Args:
        skip_metrics: Métricas ya computadas que pueden saltarse (a menos que force=True).
        force: Si True, ignora skip_metrics y ejecuta todas las métricas.
    """
    if skip_metrics is None:
        skip_metrics = []
    
    logging.info(f"{'='*60}")
    logging.info(f"{'='*60}")
    logging.info(f"INICIANDO EVALUACIÓN RAGAS")
    logging.info(f"{'='*60}")
    logging.info(f"Domain: {domain} | Task: {task} | SampleQuery: {sample_query} | SampleContext: {sample_context}")
    if skip_metrics and not force:
        logging.info(f"Métricas a saltarse (ya computadas): {skip_metrics}")
    if force:
        logging.info(f"--force activo: se re-evaluará incluso métricas ya computadas")
    logging.info(f"InputFile: {input_jsonl}")
    logging.info(f"OutputFile: {output_file}")
    logging.info(f"ConfigFile: {config_path}")
    
    cfg = load_config(path=config_path)

    logging.info(f"Configuración cargada correctamente")

    # Extraer muestras
    ragas_samples = extract_samples_from_jsonl(input_jsonl)

    # Ejecutar RAGAS
    if ragas_samples:
        logging.info(f"Iniciando evaluación RAGAS con {len(ragas_samples)} muestras")
        print("========== RAGAS Evaluation (Incremental) ==========\n")
        output_path_obj = Path(output_file)
        per_metric_dir = str(output_path_obj.parent / "by_metric")
        per_metric_prefix = output_path_obj.stem

        ragas_df, ragas_metric_list, per_metric_files = run_ragas_evaluation(
            ragas_samples,
            cfg,
            task=task,
            per_metric_output_dir=per_metric_dir,
            per_metric_output_prefix=per_metric_prefix,
            domain=domain,
            sample_query=sample_query,
            sample_context=sample_context,
            skip_metrics=skip_metrics,
            force=force,
        )

        # Resumen
        print("\nRagas scores resumen:")
        logging.info("Resumen de scores RAGAS:")
        for col in ragas_metric_list:
            vals = ragas_df[col].dropna()
            if len(vals):
                summary = f"  {col}: mean={vals.mean():.4f}  min={vals.min():.4f}  max={vals.max():.4f}"
                print(summary)
                logging.info(summary)

        print("\nExporting final output...\n")
        logging.info("Exportando resultados finales...")
        # 1) Guardar detalle por muestra en fichero auxiliar
        detailed_output = str(Path(output_file).with_name(f"{Path(output_file).stem}-samples.csv"))
        export_ragas_output(ragas_df=ragas_df, output_file=detailed_output)

        # 2) Guardar resumen solicitado por task en output_file
        export_ragas_summary(
            ragas_df=ragas_df,
            metric_names=ragas_metric_list,
            output_file=output_file,
        )

        if per_metric_files:
            print("\nFicheros por métrica generados:")
            logging.info(f"Generados {len(per_metric_files)} ficheros por métrica")
            for p in per_metric_files:
                print(f" - {p}")
                logging.debug(f"  Fichero por métrica: {p}")
        print(f"\nDetalle por muestra: {detailed_output}")
        logging.info(f"Detalle por muestra: {detailed_output}")
        print(f"Resumen por métrica: {output_file}")
        logging.info(f"Resumen por métrica: {output_file}")
    else:
        print("No hay muestras en el JSONL para evaluar con RAGAS.")
        logging.warning("No hay muestras en el JSONL para evaluar con RAGAS.")

    print(f"RAGAS evaluation complete. Output file: {output_file}")
    logging.info(f"{'='*60}")
    logging.info(f"EVALUACIÓN RAGAS COMPLETADA EXITOSAMENTE")
    logging.info(f"{'='*60}")


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Run RAGAS evaluation (incremental) from domain input",
        epilog=_samples_help_epilog(base_dir),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--domain",
        required=True,
        choices=os.listdir(Path(__file__).parent / "data"),
        help="Dominio de datos",
    )
    parser.add_argument(
        "--task",
        default="all",
        choices=["retrieval", "generation", "all", "hit"],
        help="Tipo de métricas a evaluar",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Si existe salida, la borra y recalcula (por defecto: false)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration YAML (default: config.yaml)",
    )
    parser.add_argument(
        "--input_file",
        default=None,
        help=(
            "Ruta al JSONL formateado para RAGAS (por defecto: "
            "retrieval/{model_id}/ALIA-{domain}-embeddings-results-format-query_{sample-query}-contexts_{sample-context}.jsonl)"
        ),
    )
    parser.add_argument(
        "--output_file",
        default=None,
        help=(
            "Ruta de salida (por defecto: "
            "results/ALIA-{domain}-ragas-{task}-query_{sample-query}-contexts_{sample-context}.csv)"
        ),
    )
    parser.add_argument(
        "--sample-query",
        type=int,
        default=0,
        help="Sample de queries evaluadas. 0 = todos.",
    )
    parser.add_argument(
        "--sample-context",
        type=int,
        default=0,
        help="Sample de contexts usado en retrieval. 0 = todos.",
    )
    args = parser.parse_args()
    
    if args.sample_query < 0 or args.sample_context < 0:
        raise ValueError("--sample-query y --sample-context deben ser >= 0")

    available_query = _available_query_samples_for_domain(base_dir, args.domain)
    available_context = _available_context_samples_for_domain(base_dir, args.domain)
    if args.sample_query > 0 and available_query and args.sample_query not in available_query:
        logging.warning(
            "sample-query=%s no está en detectados para %s: %s",
            args.sample_query,
            args.domain,
            available_query,
        )
    if args.sample_context > 0 and available_context and args.sample_context not in available_context:
        logging.warning(
            "sample-context=%s no está en detectados para %s: %s",
            args.sample_context,
            args.domain,
            available_context,
        )

    cfg_for_paths = load_config(path=args.config)
    embedding_model_id = _embedding_model_id_from_cfg(cfg_for_paths)
    retrieval_model_dir = Path("retrieval") / embedding_model_id
    results_model_dir = Path("results") / embedding_model_id

    input_file = (
        args.input_file
        or (
            f"{retrieval_model_dir.as_posix()}/ALIA-{args.domain}-embeddings-results-format-"
            f"query_{args.sample_query}-contexts_{args.sample_context}.jsonl"
        )
    )

    default_output_name = (
        f"ALIA-{args.domain}-ragas-{args.task}-"
        f"query_{args.sample_query}-contexts_{args.sample_context}.csv"
    )

    if args.output_file:
        user_output = Path(args.output_file)
        output_file = str(results_model_dir / user_output.name)
    else:
        output_file = str(results_model_dir / default_output_name)

    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(
                    "logs", f"STEP_5_RAGAS_{args.domain}_{embedding_model_id}_{datetime.now().strftime('%Y-%m-%d_%H.%M.%S')}.log"
                ),
                encoding="utf-8",
            ),
        ],
    )
    logging.info("Iniciando módulo step_5_run_ragas.py")

    
    logging.info(
        "Embedding model_id detectado para outputs: %s (model_name=%s)",
        embedding_model_id,
        cfg_for_paths.get("encoder-api", {}).get("model_name", ""),
    )

    input_path = (base_dir / input_file).resolve()
    output_path = (base_dir / output_file).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Verificar si el output ya existe y qué métricas están computadas
    exists, computed_metrics, missing_metrics = check_existing_output(
        str(output_path), args.task
    )

    if exists:
        print(f"\nOutput ya existe: {output_path}")
        print(f"  Métricas presentes: {computed_metrics}")
        print(f"  Métricas faltantes: {missing_metrics}")
        logging.info(f"Output ya existe: {output_path}")
        logging.info(f"Métricas presentes: {computed_metrics}")
        logging.info(f"Métricas faltantes: {missing_metrics}")

        if not missing_metrics and not args.force:
            # Todas las métricas están presentes y force no está activado
            print(
                f"\nTodas las métricas están presentes para task={args.task}. "
                f"No se recalcula (usa --force para forzar)."
            )
            logging.info(
                f"Todas las métricas están presentes para task={args.task}. "
                f"No se recalcula (usa --force para forzar)."
            )
            sys.exit(0)

        if missing_metrics:
            print(
                f"\nFaltan {len(missing_metrics)} métrica(s) para task={args.task}: {missing_metrics}\n"
            )
            logging.info(
                f"Faltan {len(missing_metrics)} métrica(s) para task={args.task}: {missing_metrics}"
            )
            print(f"Ejecutando evaluación para completar las métricas faltantes...\n")
            logging.info(
                f"Ejecutando evaluación para completar las métricas faltantes..."
            )

        if args.force:
            print(f"\n--force activo: se borrará el output existente y se recalculará.\n")
            logging.info(f"--force activo: se borrará el output existente y se recalculará.")
            output_path.unlink()
            skip_metrics = []
        else:
            # Usar las métricas computadas para saltarlas
            skip_metrics = computed_metrics
    else:
        skip_metrics = []

    main(
        domain=args.domain,
        task=args.task,
        config_path=args.config,
        input_jsonl=str(input_path),
        output_file=str(output_path),
        sample_query=args.sample_query,
        sample_context=args.sample_context,
        skip_metrics=skip_metrics,
        force=args.force,
    )
