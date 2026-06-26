"""
Genera ficheros JSONL derivados desde ALIA-administrative-duples.jsonl:

1) queries.jsonl
   - user_input <- query
   - id_passage, id_document, source_id

2) references.jsonl
   - reference <- answer
   - id_passage, id_document, source_id

3) reference_contexts.jsonl
   - reference_contexts <- [passage]
   - id_passage, id_document, source_id

Comportamiento:
- Si el fichero de salida no existe, lo crea.
- Si ya existe, añade solo registros nuevos (evita duplicados exactos).

Uso:
    python data.py --domain "biomedical"
    python data.py --domain "biomedical" --input_file "data/biomedical/ALIA-biomedical-triplets.jsonl"
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
import re, os

import polars as pl


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _read_ndjson(path: Path) -> pl.DataFrame:
    """Lee un JSONL en DataFrame de Polars."""
    if path.exists() and path.stat().st_size == 0:
        return pl.DataFrame()
    return pl.read_ndjson(
        str(path), 
        ignore_errors=True
    )


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


def _append_unique_ndjson(path: Path, new_df: pl.DataFrame) -> int:
    """Añade filas únicas a un JSONL usando Polars y devuelve el número de filas añadidas."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        new_unique = new_df.unique(maintain_order=True)
        new_unique.write_ndjson(str(path))
        return new_unique.height

    existing_df = _read_ndjson(path)
    before = existing_df.height

    combined = pl.concat([existing_df, new_df], how="diagonal_relaxed")
    final_df = combined.unique(maintain_order=True)

    added = max(0, final_df.height - before)
    final_df.write_ndjson(str(path))
    return added


def build_outputs(input_path: Path, output_dir: Path, sample: int) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"No existe el fichero de entrada: {input_path}")

    df = _read_ndjson(input_path)
    if df.height == 0:
        print("No hay filas válidas en el JSONL de entrada.")
        return

    required = [
        "id_passage_query",
        "id_passage",
        "source_id",
        "query",
        "answer",
        "passage",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        if "answer" in missing:
            print("Warning: 'answer' no encontrado, se generará con valores vacíos.")
            df = df.with_columns(pl.lit("").alias("answer"))
            missing.remove("answer")
        else:
            raise ValueError(f"Faltan columnas requeridas en el JSONL de entrada: {missing}")

    base_cols = [
        "id_passage_query", 
        "id_passage", 
        "source_id"
    ]
    if "id_document" in df.columns: base_cols.insert(2, "id_document")

    queries_df = (
        df.select(base_cols + ["query"])
        .with_columns(pl.col("query").map_elements(_safe_str, return_dtype=pl.String))
        .filter(pl.col("query") != "")
        .rename(
            {
                "id_passage_query": "id_query",
                "id_passage": "id_passage",
                "query": "user_input",
            }
        )
    )

    references_df = (
        df.select(base_cols + ["answer"])
        .with_columns(pl.col("answer").map_elements(_safe_str, return_dtype=pl.String))
        # .filter(pl.col("answer") != "")
        .rename(
            {
                "id_passage_query": "id_query",
                "id_passage": "id_passage",
                "answer": "reference",
            }
        )
    )

    reference_contexts_df = (
        df.select(base_cols + ["passage"])
        .with_columns(pl.col("passage").map_elements(_safe_str, return_dtype=pl.String))
        .filter(pl.col("passage") != "")
        .with_columns(pl.col("passage").map_elements(lambda s: [s], return_dtype=pl.List(pl.String)))
        .rename(
            {
                "id_passage_query": "id_query",
                "id_passage": "id_passage",
                "passage": "reference_contexts",
            }
        )
    )

    suffix = f"_{sample}"
    queries_path = output_dir / f"queries{suffix}.jsonl"
    references_path = output_dir / f"references{suffix}.jsonl"
    reference_contexts_path = output_dir / f"reference_contexts{suffix}.jsonl"

    q_added = _append_unique_ndjson(queries_path, queries_df)
    r_added = _append_unique_ndjson(references_path, references_df)
    rc_added = _append_unique_ndjson(reference_contexts_path, reference_contexts_df)

    print("Generación completada:")
    print(f" - queries.jsonl: {q_added} registros añadidos")
    print(f" - references.jsonl: {r_added} registros añadidos")
    print(f" - reference_contexts.jsonl: {rc_added} registros añadidos")


def main() -> None:
    base_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Genera queries/references/reference_contexts JSONL",
        epilog=_samples_help_epilog(base_dir),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Dominio para construir rutas (ej: biomedical, administrative, legal)",
    )
    parser.add_argument(
        "--input_file",
        default=None,
        help=(
            "Ruta del JSONL de entrada (si no se pasa: "
            "data/{domain}/ALIA-{domain}-triplets-{sample}.jsonl; "
            "si sample=0 usa el mayor detectado)"
        ),
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help=(
            "Directorio de salida (si no se pasa: "
            "data/{domain}/ALIA-{domain}-triplets-{sample}/)"
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help=(
            "Tamaño de muestra a procesar. 0 = todos los disponibles. "
            "El input por defecto será ALIA-{domain}-triplets-{sample}.jsonl "
            "(o el mayor disponible si sample=0)."
        ),
    )
    args = parser.parse_args()

    if args.sample < 0:
        raise ValueError("--sample debe ser >= 0")

    domain_samples = _available_query_samples_for_domain(base_dir, args.domain)
    if args.sample > 0 and domain_samples and args.sample not in domain_samples:
        print(
            f"Warning: sample={args.sample} no está en detectados para {args.domain}: {domain_samples}"
        )

    if args.sample == 0:
        if domain_samples:
            inferred_sample = max(domain_samples)
            default_input = (
                f"data/{args.domain}/ALIA-{args.domain}-triplets-{inferred_sample}.jsonl"
            )
        else:
            default_input = f"data/{args.domain}/ALIA-{args.domain}-triplets.jsonl"
    else:
        default_input = f"data/{args.domain}/ALIA-{args.domain}-triplets-{args.sample}.jsonl"

    default_output = f"data/{args.domain}/ALIA-{args.domain}-triplets-{args.sample}/"

    input_file = args.input_file or default_input
    output_dir_arg = args.output_dir or default_output

    input_path = (base_dir / input_file).resolve()
    output_dir = (base_dir / output_dir_arg).resolve()

    build_outputs(input_path=input_path, output_dir=output_dir, sample=args.sample)


if __name__ == "__main__":
    main()
