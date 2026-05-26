import argparse
from pathlib import Path
from typing import Any
import logging
import os
import re
import sys
from datetime import datetime
import polars as pl
import yaml

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


def format_for_ragas(
    retrieval_results_path: Path,
    references_path: Path,
    reference_contexts_path: Path,
    output_path: Path,
) -> None:
    if not retrieval_results_path.exists():
        raise FileNotFoundError(f"No existe fichero de resultados de retrieval: {retrieval_results_path}")
    if not references_path.exists():
        raise FileNotFoundError(f"No existe references.jsonl: {references_path}")
    if not reference_contexts_path.exists():
        raise FileNotFoundError(f"No existe reference_contexts.jsonl: {reference_contexts_path}")

    retrieval_df = _read_ndjson(retrieval_results_path)
    references_df = _read_ndjson(references_path)
    reference_ctx_df = _read_ndjson(reference_contexts_path)

    required_retrieval = ["id_query", "user_input", "retrieved_contexts"]
    optional_retrieval = ["id_passage", "id_retrieved_contexts"]
    required_references = ["id_query", "reference"]
    required_reference_ctx = ["id_query", "reference_contexts"]

    missing_ret = [c for c in required_retrieval if c not in retrieval_df.columns]
    missing_ref = [c for c in required_references if c not in references_df.columns]
    missing_refctx = [c for c in required_reference_ctx if c not in reference_ctx_df.columns]

    if missing_ret:
        raise ValueError(f"Faltan columnas en resultados retrieval: {missing_ret}")
    if missing_ref:
        raise ValueError(f"Faltan columnas en references.jsonl: {missing_ref}")
    if missing_refctx:
        raise ValueError(f"Faltan columnas en reference_contexts.jsonl: {missing_refctx}")
    
    # Advertencia si faltan campos opcionales necesarios para hit@1
    missing_optional = [c for c in optional_retrieval if c not in retrieval_df.columns]
    if missing_optional:
        logging.warning(
            f"Campos opcionales faltantes en retrieval: {missing_optional}. "
            "La métrica hit@1 en step_5 registrará NaN para estas muestras."
        )

    if retrieval_df.height == 0:
        raise ValueError("El fichero de resultados retrieval está vacío")

    # Mantener 1 fila por id_query en ficheros auxiliares para evitar duplicados tras join.
    # Si references trae id_passage, lo preservamos como fallback para hit@1.
    if "id_passage" in references_df.columns:
        references_clean = (
            references_df.select(["id_query", "reference", "id_passage"])
            .with_columns(
                pl.col("id_query").cast(pl.Utf8),
                pl.col("reference").cast(pl.Utf8),
                pl.col("id_passage").cast(pl.Utf8).alias("id_passage_reference"),
            )
            .drop("id_passage")
            .unique(subset=["id_query"], keep="first", maintain_order=True)
        )
    else:
        references_clean = (
            references_df.select(["id_query", "reference"])
            .with_columns(
                pl.col("id_query").cast(pl.Utf8),
                pl.col("reference").cast(pl.Utf8),
                pl.lit(None, dtype=pl.Utf8).alias("id_passage_reference"),
            )
            .unique(subset=["id_query"], keep="first", maintain_order=True)
        )

    reference_ctx_clean = (
        reference_ctx_df.select(["id_query", "reference_contexts"])
        .with_columns(pl.col("id_query").cast(pl.Utf8))
        .unique(subset=["id_query"], keep="first", maintain_order=True)
    )

    retrieval_clean = retrieval_df.with_columns(pl.col("id_query").cast(pl.Utf8))

    merged = (
        retrieval_clean.join(references_clean, on="id_query", how="left")
        .join(reference_ctx_clean, on="id_query", how="left")
    )

    # Normalizar columnas de IDs para hit@1.
    id_passage_candidates = []
    if "id_passage" in merged.columns:
        id_passage_candidates.append(pl.col("id_passage").cast(pl.Utf8, strict=False))
    if "id_passage_reference" in merged.columns:
        id_passage_candidates.append(pl.col("id_passage_reference").cast(pl.Utf8, strict=False))

    if id_passage_candidates:
        merged = merged.with_columns(pl.coalesce(id_passage_candidates).alias("id_passage"))
    else:
        merged = merged.with_columns(pl.lit(None, dtype=pl.Utf8).alias("id_passage"))

    if "id_retrieved_contexts" not in merged.columns:
        merged = merged.with_columns(
            pl.lit([], dtype=pl.List(pl.Utf8)).alias("id_retrieved_contexts")
        )
    else:
        merged = merged.with_columns(
            pl.when(pl.col("id_retrieved_contexts").is_null())
            .then(pl.lit([], dtype=pl.List(pl.Utf8)))
            .otherwise(
                pl.col("id_retrieved_contexts")
                .cast(pl.List(pl.Utf8), strict=False)
                .fill_null(pl.lit([], dtype=pl.List(pl.Utf8)))
            )
            .alias("id_retrieved_contexts")
        )

    merged = merged.with_columns(
        [
            pl.col("id_passage").alias("id_reference_context"),
            pl.when(pl.col("id_retrieved_contexts").list.len() > 0)
            .then(pl.col("id_retrieved_contexts").list.get(0))
            .otherwise(pl.lit(None, dtype=pl.Utf8))
            .alias("id_retrieved_context"),
        ]
    )

    # Esquema requerido por step_5_run_ragas.py
    # Incluye id_passage e id_retrieved_contexts para la métrica hit@1
    select_cols = [
        pl.col("id_query").alias("id"),
        pl.col("user_input"),
        pl.col("reference").alias("response"),
        pl.col("reference"),
        pl.col("retrieved_contexts"),
        pl.col("reference_contexts"),
        pl.col("id_passage"),
        pl.col("id_retrieved_contexts"),
        pl.col("id_reference_context"),
        pl.col("id_retrieved_context"),
    ]

    out_df = merged.select(select_cols)

    # Rellenos por seguridad de tipos esperados por RAGAS.
    cast_cols = [
        pl.col("id").cast(pl.Utf8),
        pl.col("user_input").cast(pl.Utf8),
        pl.col("response").cast(pl.Utf8),
        pl.col("reference").cast(pl.Utf8),
        pl.when(pl.col("retrieved_contexts").is_null())
        .then(pl.lit([], dtype=pl.List(pl.Utf8)))
        .otherwise(pl.col("retrieved_contexts"))
        .alias("retrieved_contexts"),
        pl.when(pl.col("reference_contexts").is_null())
        .then(pl.lit([], dtype=pl.List(pl.Utf8)))
        .otherwise(pl.col("reference_contexts"))
        .alias("reference_contexts"),
    ]
    
    cast_cols.extend(
        [
            pl.when(pl.col("id_retrieved_contexts").is_null())
            .then(pl.lit([], dtype=pl.List(pl.Utf8)))
            .otherwise(
                pl.col("id_retrieved_contexts")
                .cast(pl.List(pl.Utf8), strict=False)
                .fill_null(pl.lit([], dtype=pl.List(pl.Utf8)))
            )
            .alias("id_retrieved_contexts"),
            pl.col("id_passage").cast(pl.Utf8, strict=False),
            pl.col("id_reference_context").cast(pl.Utf8, strict=False),
            pl.col("id_retrieved_context").cast(pl.Utf8, strict=False),
        ]
    )
    
    out_df = out_df.with_columns(cast_cols)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.write_ndjson(str(output_path))

    logging.info(f"Filas de entrada retrieval: {retrieval_df.height}")
    logging.info(f"Filas de salida formateadas: {out_df.height}")
    logging.info(f"Salida RAGAS: {output_path}")


def main() -> None:
    base_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description=(
            "Formatear los resultados de la recuperación para evaluar el modelo con RAGAS "
            "retrieval/{model_id}/ALIA-{domain}-embeddings-results-format.jsonl"
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
        "--input_file",
        default=None,
        help=(
            "Ruta del fichero retrieval de entrada (por defecto: "
            "retrieval/{model_id}/ALIA-{domain}-embeddings-results-query_{sample-query}-contexts_{sample-context}.jsonl)"
        ),
    )
    parser.add_argument(
        "--references_file",
        default=None,
        help=(
            "Ruta de references.jsonl (por defecto: "
            "data/{domain}/ALIA-{domain}-triplets-{sample-query}/references_{sample-query}.jsonl)"
        ),
    )
    parser.add_argument(
        "--reference_contexts_file",
        default=None,
        help=(
            "Ruta de reference_contexts.jsonl (por defecto: "
            "data/{domain}/ALIA-{domain}-triplets-{sample-query}/reference_contexts_{sample-query}.jsonl)"
        ),
    )
    parser.add_argument(
        "--output_file",
        default=None,
        help=(
            "Ruta de salida (por defecto: "
            "retrieval/{model_id}/ALIA-{domain}-embeddings-results-format-query_{sample-query}-contexts_{sample-context}.jsonl)"
        ),
    )
    parser.add_argument(
        "--sample-query",
        type=int,
        default=0,
        help="Sample de queries a formatear. 0 = todos.",
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
                os.path.join(
                    "logs", f"STEP_4_FORMAT_{args.domain}_{embedding_model_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                ),
                encoding="utf-8",
            ),
        ],
    )
    logging.info("Iniciando módulo step_4_format_for_ragas.py")
    
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

    input_file = (
        args.input_file
        or (
            f"retrieval/{embedding_model_id}/ALIA-{args.domain}-embeddings-results-"
            f"query_{args.sample_query}-contexts_{args.sample_context}.jsonl"
        )
    )
    references_file = (
        args.references_file
        or f"data/{args.domain}/ALIA-{args.domain}-triplets-{args.sample_query}/references_{args.sample_query}.jsonl"
    )
    reference_contexts_file = (
        args.reference_contexts_file
        or (
            f"data/{args.domain}/ALIA-{args.domain}-triplets-{args.sample_query}/"
            f"reference_contexts_{args.sample_query}.jsonl"
        )
    )
    output_file = (
        args.output_file
        or (
            f"retrieval/{embedding_model_id}/ALIA-{args.domain}-embeddings-results-format-"
            f"query_{args.sample_query}-contexts_{args.sample_context}.jsonl"
        )
    )

    logging.info(
        "Embedding model_id detectado para format retrieval: %s (model_name=%s)",
        embedding_model_id,
        (cfg_for_paths.get("encoder-api") or {}).get("model_name", ""),
    )

    retrieval_results_path = (base_dir / input_file).resolve()
    references_path = (base_dir / references_file).resolve()
    reference_contexts_path = (base_dir / reference_contexts_file).resolve()
    output_path = (base_dir / output_file).resolve()

    if output_path.exists() and not args.force:
        logging.info(
            f"La salida ya existe y --force no está activado. No se recalcula: {output_path}"
        )
        return

    if output_path.exists() and args.force:
        logging.info(f"--force activo: borrando salida existente {output_path}")
        output_path.unlink()

    format_for_ragas(
        retrieval_results_path=retrieval_results_path,
        references_path=references_path,
        reference_contexts_path=reference_contexts_path,
        output_path=output_path,
    )

if __name__ == "__main__":
    main()