from __future__ import annotations

import argparse, os, sys
from pathlib import Path
from typing import Any
import re

import faiss
import numpy as np
import polars as pl
import yaml
from openai import OpenAI

import logging
from datetime import datetime

EMBEDDING_MAX_TOKENS = 8192

def _available_query_samples_for_domain(base_dir: Path, domain: str) -> list[int]:
    data_dir = base_dir / "data" / domain
    if not data_dir.exists():
        return []

    samples: set[int] = set()
    for p in data_dir.glob(f"ALIA-{domain}-contexts-*.jsonl"):
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
    """Lee JSONL en un DataFrame de Polars."""
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


def _to_float32_matrix(vectors: list[list[float]]) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("Los embeddings deben tener forma 2D [n, dim].")
    return arr


def _truncate_to_token_limit(text: str, max_tokens: int) -> tuple[str, bool]: 
    if (len(text) * 3.7) <= max_tokens:
        return text, False
    max_chars = int(max_tokens * 3.7)
    return text[:max_chars], True


def _embed_passages(
    passages: list[str],
    client: OpenAI,
    model_name: str,
    batch_size: int,
) -> np.ndarray:
    """Obtiene embeddings por lotes usando API OpenAI-compatible (vLLM)."""
    if not passages:
        raise ValueError("No hay pasajes para vectorizar.")
    if batch_size <= 0:
        raise ValueError("batch_size debe ser mayor que 0.")

    all_vectors: list[list[float]] = []
    total = len(passages)
    total_truncated = 0
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        raw_batch = passages[start:end]
        batch: list[str] = []
        for text in raw_batch:
            truncated_text, was_truncated = _truncate_to_token_limit(
                text, EMBEDDING_MAX_TOKENS
            )
            if was_truncated:
                total_truncated += 1
            batch.append(truncated_text)

        resp = client.embeddings.create(model=model_name, input=batch)
        ordered = sorted(resp.data, key=lambda d: d.index)
        batch_vectors = [item.embedding for item in ordered]
        all_vectors.extend(batch_vectors)

        logging.info(f"Embeddings: {end}/{total}")

    if total_truncated:
        logging.warning(
            "Se truncaron %s textos a %s tokens antes de vectorizar.",
            total_truncated,
            EMBEDDING_MAX_TOKENS,
        )

    return _to_float32_matrix(all_vectors)


def build_faiss_db(
    input_path: Path,
    config_path: Path,
    output_dir: Path,
    index_name: str,
    metadata_name: str,
    normalize: bool,
    batch_size: int,
) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"No existe el fichero de entrada: {input_path}")
    if not config_path.exists():
        raise FileNotFoundError(f"No existe el fichero de configuración: {config_path}")

    cfg = _load_config(config_path)
    encoder_cfg = cfg.get("encoder-api", {})

    api_key = encoder_cfg.get("api_key")
    base_url = encoder_cfg.get("base_url")
    model_name = encoder_cfg.get("model_name")

    if not api_key or not base_url or not model_name:
        raise ValueError(
            "Faltan campos en encoder-api del config.yaml: api_key, base_url o model_name."
        )

    df = _read_ndjson(input_path)
    if df.height == 0:
        raise ValueError("El JSONL de entrada no contiene filas válidas.")

    required = ["id_passage", "passage"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en el JSONL: {missing}")

    # id_passage = identificador único. El resto de columnas se conserva como metadatos.
    work_df = (
        df.with_columns(
            [
                pl.col("id_passage").cast(pl.Utf8),
                pl.col("passage").cast(pl.Utf8),
            ]
        )
        .filter(pl.col("id_passage").is_not_null() & (pl.col("id_passage") != ""))
        .filter(pl.col("passage").is_not_null() & (pl.col("passage") != ""))
        .unique(subset=["id_passage"], keep="first", maintain_order=True)
    )

    if work_df.height == 0:
        raise ValueError("No hay filas con id_passage y passage válidos tras el filtrado.")

    passages = work_df["passage"].to_list()

    client = OpenAI(
        api_key=api_key, 
        base_url=base_url
    )
    vectors = _embed_passages(
        passages=passages,
        client=client,
        model_name=model_name,
        batch_size=batch_size,
    )

    if normalize:
        faiss.normalize_L2(vectors)

    dim = vectors.shape[1]
    base_index: faiss.Index
    if normalize:
        # Producto interno con vectores normalizados ~ similitud coseno.
        base_index = faiss.IndexFlatIP(dim)
    else:
        base_index = faiss.IndexFlatL2(dim)

    index = faiss.IndexIDMap2(base_index)

    # IDs internos numéricos para FAISS; id_passage queda en metadatos.
    int_ids = np.arange(work_df.height, dtype=np.int64)
    vectors = np.ascontiguousarray(vectors, dtype=np.float32)
    int_ids = np.ascontiguousarray(int_ids, dtype=np.int64)

    # Firma en runtime del wrapper de FAISS: add_with_ids(x, xids)
    add_with_ids_fn = getattr(index, "add_with_ids")
    add_with_ids_fn(vectors, int_ids)

    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / index_name
    metadata_path = output_dir / metadata_name

    faiss.write_index(index, str(index_path))

    metadata_df = work_df.with_columns(pl.Series(name="faiss_int_id", values=int_ids))
    metadata_df.write_ndjson(str(metadata_path))

    logging.info("Base vectorial creada correctamente:")
    logging.info(f" - Índice FAISS: {index_path}")
    logging.info(f" - Metadatos: {metadata_path}")
    logging.info(f" - Registros indexados: {work_df.height}")
    logging.info(f" - Dimensión embedding: {dim}")
    logging.info(f" - Modelo embeddings: {model_name}")


def main() -> None:
    base_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Genera una base de datos vectorial con FAISS",
        epilog=_samples_help_epilog(base_dir),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--domain",
        required=True,
        choices=os.listdir(Path(__file__).parent / "data"),
        help="Dominio para construir rutas (ej: biomedical, legal, heritage)",
    )
    parser.add_argument(
        "--input_file",
        default=None,
        help=(
            "Ruta del JSONL de entrada (si no se pasa: "
            "data/{domain}/ALIA-{domain}-contexts-{sample}.jsonl; "
            "si sample=0 usa el mayor detectado)"
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Ruta al fichero de configuración YAML (por defecto: config.yaml)",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help=(
            "Directorio de salida (por defecto: "
            "data/{domain}/ALIA-{domain}-contexts-{sample}/vector_db/{model_id})"
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help=(
            "Tamaño de muestra para contexts. 0 = todos los disponibles "
            "(usa el mayor sample detectado)."
        ),
    )
    parser.add_argument(
        "--index_name",
        default="faiss.index",
        help="Nombre del fichero del índice FAISS",
    )
    parser.add_argument(
        "--metadata_name",
        default="metadata.jsonl",
        help="Nombre del fichero JSONL con metadatos",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=64,
        help="Tamaño de lote para llamadas de embeddings",
    )
    parser.add_argument(
        "--no_normalize",
        action="store_true",
        help="Desactiva normalización L2 (por defecto activada)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Si existe salida, la borra y recalcula (por defecto: false)",
    )

    args = parser.parse_args()

    if args.sample < 0:
        raise ValueError("--sample debe ser >= 0")

    config_path = (base_dir / args.config).resolve()
    cfg_for_paths = _load_config(config_path)
    embedding_model_id = _embedding_model_id_from_cfg(cfg_for_paths)
    
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join("logs", f"STEP_2_FAISS_database_{args.domain}_{embedding_model_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
                encoding="utf-8",
            )
        ]
    )
    logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

    domain_samples = _available_context_samples_for_domain(base_dir, args.domain)
    if args.sample > 0 and domain_samples and args.sample not in domain_samples:
        logging.warning(
            "sample=%s no está en detectados para %s: %s",
            args.sample,
            args.domain,
            domain_samples,
        )

    if args.sample == 0:
        if domain_samples:
            inferred_sample = max(domain_samples)
            default_input = (
                f"data/{args.domain}/ALIA-{args.domain}-contexts-{inferred_sample}.jsonl"
            )
        else:
            default_input = f"data/{args.domain}/ALIA-{args.domain}-contexts.jsonl"
    else:
        default_input = f"data/{args.domain}/ALIA-{args.domain}-contexts-{args.sample}.jsonl"

    default_output = (
        f"data/{args.domain}/ALIA-{args.domain}-contexts-{args.sample}/"
        f"vector_db/{embedding_model_id}"
    )

    input_file = args.input_file or default_input
    output_dir_arg = args.output_dir or default_output

    input_path = (base_dir / input_file).resolve()
    output_dir = (base_dir / output_dir_arg).resolve()

    logging.info(
        "Embedding model_id detectado para vector_db: %s (model_name=%s)",
        embedding_model_id,
        (cfg_for_paths.get("encoder-api") or {}).get("model_name", ""),
    )

    index_path = output_dir / args.index_name
    metadata_path = output_dir / args.metadata_name

    if index_path.exists() and metadata_path.exists() and not args.force:
        logging.info(
            f"La salida ya existe y --force no está activado. No se recalcula: {output_dir}"
        )
        return

    if (index_path.exists() or metadata_path.exists()) and args.force:
        logging.info(f"--force activo: borrando salida existente en {output_dir}")
        if index_path.exists():
            index_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()

    build_faiss_db(
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        index_name=args.index_name,
        metadata_name=args.metadata_name,
        normalize=not args.no_normalize,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
