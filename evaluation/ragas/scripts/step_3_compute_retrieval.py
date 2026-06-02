from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import polars as pl
import yaml
from openai import OpenAI

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


def _read_ndjson(path: Path) -> pl.DataFrame:
    return pl.read_ndjson(str(path), ignore_errors=True)


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _embedding_model_id_from_cfg(cfg: dict[str, Any]) -> str:
    model_name = str((cfg.get("encoder-api") or {}).get("model_name") or "").strip()
    if not model_name:
        return "unknown-model"
    model_id = model_name.split("/")[-1].strip()
    return model_id or "unknown-model"


def _embed_texts(
    texts: list[str],
    client: OpenAI,
    model_name: str,
    batch_size: int,
) -> np.ndarray:
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    if batch_size <= 0:
        raise ValueError("batch_size debe ser mayor que 0")

    all_vectors: list[list[float]] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = texts[start:end]
        resp = client.embeddings.create(model=model_name, input=batch)
        ordered = sorted(resp.data, key=lambda d: d.index)
        all_vectors.extend(item.embedding for item in ordered)
        logging.info(f"Embeddings consultas: {end}/{total}")

    arr = np.asarray(all_vectors, dtype=np.float32)
    return np.ascontiguousarray(arr, dtype=np.float32)


def _metadata_by_faiss_id(metadata_df: pl.DataFrame) -> dict[int, dict[str, Any]]:
    if "faiss_int_id" not in metadata_df.columns:
        metadata_df = metadata_df.with_row_index(name="faiss_int_id")

    result: dict[int, dict[str, Any]] = {}
    for row in metadata_df.iter_rows(named=True):
        result[int(row["faiss_int_id"])] = row
    return result


def _to_confidence(score: float, metric_type: int) -> float:
    # Si el índice usa L2, convertimos distancia a (0, 1] para interpretarlo como confianza.
    if metric_type == faiss.METRIC_L2:
        return float(1.0 / (1.0 + max(score, 0.0)))
    # IP / coseno normalizado: score ya es similitud.
    return float(score)


def compute_retrieval(
    domain: str,
    config_path: Path,
    queries_path: Path,
    index_path: Path,
    metadata_path: Path,
    output_path: Path,
    top_k: int,
    batch_size: int,
) -> None:
    if not config_path.exists():
        raise FileNotFoundError(f"No existe config: {config_path}")
    if not queries_path.exists():
        raise FileNotFoundError(f"No existe queries.jsonl: {queries_path}")
    if not index_path.exists():
        raise FileNotFoundError(f"No existe índice FAISS: {index_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"No existe metadata.jsonl: {metadata_path}")

    cfg = _load_config(config_path)
    encoder_cfg = cfg.get("encoder-api", {})
    api_key = encoder_cfg.get("api_key")
    base_url = encoder_cfg.get("base_url")
    model_name = encoder_cfg.get("model_name")

    if not api_key or not base_url or not model_name:
        raise ValueError(
            "Faltan campos en encoder-api del config.yaml: api_key, base_url o model_name."
        )

    queries_df = _read_ndjson(queries_path)
    metadata_df = _read_ndjson(metadata_path)

    required_queries = [
        "source_id", 
        "id_passage", 
        "id_query", 
        "user_input"
    ]
    if "id_document" in queries_df.columns: required_queries.insert(1, "id_document")
    missing_q = [c for c in required_queries if c not in queries_df.columns]
    if missing_q:
        raise ValueError(f"Faltan columnas en queries.jsonl: {missing_q}")
    if queries_df.height == 0:
        raise ValueError("queries.jsonl está vacío")
    if metadata_df.height == 0:
        raise ValueError("metadata.jsonl está vacío")

    queries_df = (
        queries_df.with_columns(pl.col("user_input").cast(pl.Utf8))
        .filter(pl.col("user_input").is_not_null() & (pl.col("user_input") != ""))
    )
    if queries_df.height == 0:
        raise ValueError("No hay consultas válidas en queries.jsonl")

    index = faiss.read_index(str(index_path))
    metric_type = int(getattr(index, "metric_type", faiss.METRIC_INNER_PRODUCT))
    metadata_lookup = _metadata_by_faiss_id(metadata_df)

    k = min(top_k, len(metadata_lookup))
    if k <= 0:
        raise ValueError("No hay metadatos para recuperar contextos")

    client = OpenAI(api_key=api_key, base_url=base_url)
    queries_list = queries_df["user_input"].to_list()
    qvecs = _embed_texts(queries_list, client, model_name, batch_size=batch_size)

    # Si el índice se creó normalizado (IP), normalizamos queries por defecto.
    if metric_type != faiss.METRIC_L2:
        faiss.normalize_L2(qvecs)

    distances, indices = index.search(qvecs, k)

    out_rows: list[dict[str, Any]] = []
    query_rows = queries_df.iter_rows(named=True)

    for i, qrow in enumerate(query_rows):
        retrieved_ids: list[str] = []
        retrieved_texts: list[str] = []
        confidences: list[float] = []

        for score, idx_val in zip(distances[i], indices[i]):
            idx_int = int(idx_val)
            if idx_int < 0:
                continue

            mrow = metadata_lookup.get(idx_int)
            if mrow is None:
                continue

            retrieved_ids.append(str(mrow.get("id_passage", "")))
            retrieved_texts.append(str(mrow.get("passage", "")))
            confidences.append(_to_confidence(float(score), metric_type))

        out_rows.append(
            {
                "source_id": qrow.get("source_id"),
                "id_document": qrow.get("id_document"),
                "id_passage": qrow.get("id_passage"),
                "id_query": qrow.get("id_query"),
                "user_input": qrow.get("user_input"),
                "id_retrieved_contexts": retrieved_ids,
                "retrieved_contexts": retrieved_texts,
                "confidences": confidences,
            }
        )

        if (i + 1) % 100 == 0 or (i + 1) == queries_df.height:
            logging.info(f"Consultas procesadas: {i + 1}/{queries_df.height}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(out_rows).write_ndjson(str(output_path))

    logging.info(f"Dominio: {domain}")
    logging.info(f"Consultas totales: {queries_df.height}")
    logging.info(f"Top-k: {k}")
    logging.info(f"Modelo embeddings: {model_name}")
    logging.info(f"Salida: {output_path}")


def main() -> None:
    base_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description=(
            "Calcula retrieval por embeddings para todas las consultas y genera "
            "retrieval/{model_id}/ALIA-{domain}-embeddings-results.jsonl"
        ),
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
        "--force",
        action="store_true",
        help="Si existe salida, la borra y recalcula (por defecto: false)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Ruta al config YAML (por defecto: config.yaml)",
    )
    parser.add_argument(
        "--queries_file",
        default=None,
        help=(
            "Ruta a queries.jsonl (por defecto: "
            "data/{domain}/ALIA-{domain}-triplets-{sample-query}/queries_{sample-query}.jsonl)"
        ),
    )
    parser.add_argument(
        "--index_file",
        default=None,
        help=(
            "Ruta al índice FAISS (por defecto: "
            "data/{domain}/ALIA-{domain}-contexts-{sample-context}/vector_db/{model_id}/faiss.index)"
        ),
    )
    parser.add_argument(
        "--metadata_file",
        default=None,
        help=(
            "Ruta a metadata.jsonl (por defecto: "
            "data/{domain}/ALIA-{domain}-contexts-{sample-context}/vector_db/{model_id}/metadata.jsonl)"
        ),
    )
    parser.add_argument(
        "--output_file",
        default=None,
        help=(
            "Ruta de salida (por defecto: retrieval/{model_id}/ALIA-{domain}-embeddings-results.jsonl)"
        ),
    )
    parser.add_argument(
        "--top_k",
        type=int,
        default=5,
        help="Número de pasajes a recuperar por consulta (por defecto: 5)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=64,
        help="Tamaño de lote para embeddings de consultas",
    )
    parser.add_argument(
        "--sample-query",
        type=int,
        default=0,
        help="Sample de queries a computar. 0 = todos.",
    )
    parser.add_argument(
        "--sample-context",
        type=int,
        default=0,
        help="Sample de contexts de la base vectorial a usar. 0 = todos.",
    )

    args = parser.parse_args()

    if args.top_k <= 0:
        raise ValueError("top_k debe ser mayor que 0")
    if args.batch_size <= 0:
        raise ValueError("batch_size debe ser mayor que 0")
    if args.sample_query < 0 or args.sample_context < 0:
        raise ValueError("--sample-query y --sample-context deben ser >= 0")

    config_path = (base_dir / args.config).resolve()
    cfg_for_paths = _load_config(config_path)
    embedding_model_id = _embedding_model_id_from_cfg(cfg_for_paths)

    available_query = _available_query_samples_for_domain(base_dir, args.domain)
    available_context = _available_context_samples_for_domain(base_dir, args.domain)

    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join("logs", f"STEP_3_Retrieval_{args.domain}_{embedding_model_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
                encoding="utf-8",
            )
        ]
    )
    logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

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

    queries_file = (
        args.queries_file
        or f"data/{args.domain}/ALIA-{args.domain}-triplets-{args.sample_query}/queries_{args.sample_query}.jsonl"
    )
    index_file = (
        args.index_file
        or (
            f"data/{args.domain}/ALIA-{args.domain}-contexts-{args.sample_context}/"
            f"vector_db/{embedding_model_id}/faiss.index"
        )
    )
    metadata_file = (
        args.metadata_file
        or (
            f"data/{args.domain}/ALIA-{args.domain}-contexts-{args.sample_context}/"
            f"vector_db/{embedding_model_id}/metadata.jsonl"
        )
    )
    output_file = (
        args.output_file
        or (
            f"retrieval/{embedding_model_id}/ALIA-{args.domain}-embeddings-results-"
            f"query_{args.sample_query}-contexts_{args.sample_context}.jsonl"
        )
    )

    logging.info(
        "Embedding model_id detectado para retrieval: %s (model_name=%s)",
        embedding_model_id,
        (cfg_for_paths.get("encoder-api") or {}).get("model_name", ""),
    )

    queries_path = (base_dir / queries_file).resolve()
    index_path = (base_dir / index_file).resolve()
    metadata_path = (base_dir / metadata_file).resolve()
    output_path = (base_dir / output_file).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # DEBUG de todas las rutas antes de computar retrieval
    logging.info(f"Rutas usadas para retrieval:")
    logging.info(f"  Config: {config_path}")
    logging.info(f"  Base: {base_dir}")
    logging.info(f"  Queries: {queries_path}")
    logging.info(f"  Índice FAISS: {index_path}")
    logging.info(f"  \t{index_file}")
    logging.info(f"  Metadata: {metadata_path}")
    logging.info(f"  Salida: {output_path}")

    if output_path.exists() and not args.force:
        logging.info(
            f"La salida ya existe y --force no está activado. No se recalcula: {output_path}"
        )
        return

    if output_path.exists() and args.force:
        logging.info(f"--force activo: borrando salida existente {output_path}")
        output_path.unlink()

    compute_retrieval(
        domain=args.domain,
        config_path=config_path,
        queries_path=queries_path,
        index_path=index_path,
        metadata_path=metadata_path,
        output_path=output_path,
        top_k=args.top_k,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
