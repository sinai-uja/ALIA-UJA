import os
import sys
import yaml
import argparse
import logging
import multiprocessing

# Configurar el método de inicio antes de importar datatrove (Best Practice)
if __name__ == "__main__":
    try:
        multiprocessing.set_start_method("forkserver", force=True)
    except RuntimeError:
        pass

from datatrove.executor.local import LocalPipelineExecutor
from datatrove.pipeline.readers import JsonlReader
from datatrove.pipeline.writers.jsonl import JsonlWriter
from datatrove.pipeline.filters import (
    GopherQualityFilter,
    GopherRepetitionFilter,
    LanguageFilter,
    FineWebQualityFilter,
)
from datatrove.pipeline.dedup import (
    MinhashDedupSignature,
    MinhashDedupBuckets,
    MinhashDedupCluster,
    MinhashDedupFilter,
)
from datatrove.pipeline.dedup.minhash import MinhashConfig
from datatrove.pipeline.formatters import FTFYFormatter, PIIFormatter, SymbolLinesFormatter
from datatrove.utils.hashing import HashConfig

# Configuración de logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_args():
    parser = argparse.ArgumentParser(description="Datatrove Curation Pipeline")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    parser.add_argument("--tasks", type=int, default=25, help="Número de procesos paralelos")
    return parser.parse_args()

def load_config():
    """Carga la configuración desde el YAML adyacente."""
    config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config_es.yaml")
    if not os.path.exists(config_path):
        logging.error(f"No se encontró el fichero de configuración: {config_path}")
        sys.exit(1)
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def get_paths(cfg, name, domain, version):
    """Calcula las rutas de entrada y salida basándose en la versión."""
    if version == -1:
        input_path = cfg["INPUT_PATH"].format(name=name, domain=domain)
        output_path = cfg["OUTPUT_PATH"].format(name=name, domain=domain)
    else:
        input_path = cfg["INPUT_PATH_VERSION"].format(name=name, domain=domain, version=version)
        output_path = cfg["OUTPUT_PATH_VERSION"].format(name=name, domain=domain, version=version)
    
    return input_path, output_path

def step_language_filter(input_path, output_base, cfg, tasks):
    """Paso 1: Filtrado de idioma."""
    logging.info(">>> Iniciando Paso 1: Filtrado de Idioma")
    
    step_output = os.path.join(output_base, "01.es")
    excluded_output = os.path.join(output_base, "01.filtered-out")
    
    pipeline = [
        JsonlReader(input_path, glob_pattern="*.jsonl"),
        LanguageFilter(
            language_threshold=cfg["language_score"],
            languages=("es",),
            exclusion_writer=JsonlWriter(excluded_output)
        ),
        JsonlWriter(step_output)
    ]

    LocalPipelineExecutor(
        pipeline=pipeline,
        tasks=tasks,
        logging_dir=os.path.join(output_base, "logs/01_language")
    ).run()
    
    return step_output

def step_deduplication(input_path, output_base, cfg, tasks):
    """Paso 2: Deduplicación MinHash (4 sub-etapas)."""
    logging.info(">>> Iniciando Paso 2: Deduplicación MinHash")

    # Rutas intermedias
    sig_path = os.path.join(output_base, "minhash", "signatures")
    buckets_path = os.path.join(output_base, "minhash", "buckets")
    remove_ids = os.path.join(output_base, "minhash", "remove_ids")
    dedup_output = os.path.join(output_base, "02.deduplicated")

    minhash_cfg = MinhashConfig(
        hash_config=HashConfig(hash_fc="xxhash", precision=64),
        num_buckets=cfg.get("minhash_buckets", 25), # Parametrizable desde yaml o default
        hashes_per_bucket=cfg.get("minhash_hashes", 12),
        n_grams=cfg.get("minhash_ngrams", 5),
    )

    # 2.1 Firmas
    logging.info("  > 2.1 Signatures")
    LocalPipelineExecutor([
        JsonlReader(input_path),
        MinhashDedupSignature(output_folder=sig_path, config=minhash_cfg, language="es"),
    ], tasks=tasks, logging_dir=os.path.join(output_base, "logs/mh1")).run()

    # 2.2 Buckets
    logging.info("  > 2.2 Buckets")
    LocalPipelineExecutor([
        MinhashDedupBuckets(input_folder=sig_path, output_folder=buckets_path, config=minhash_cfg)
    ], tasks=tasks, logging_dir=os.path.join(output_base, "logs/mh2")).run()

    # 2.3 Cluster (Normalmente single-threaded o low task count por la naturaleza del clustering)
    logging.info("  > 2.3 Cluster")
    LocalPipelineExecutor([
        MinhashDedupCluster(input_folder=buckets_path, output_folder=remove_ids, config=minhash_cfg)
    ], tasks=1, logging_dir=os.path.join(output_base, "logs/mh3")).run()

    # 2.4 Filtro Final
    logging.info("  > 2.4 Filter")
    LocalPipelineExecutor([
        JsonlReader(input_path),
        MinhashDedupFilter(input_folder=remove_ids),
        JsonlWriter(dedup_output)
    ], tasks=tasks, logging_dir=os.path.join(output_base, "logs/mh4")).run()

    return dedup_output

def step_quality_filter(input_path, output_base, cfg, tasks):
    """Paso 3: Filtros de calidad y formateo final."""
    logging.info(">>> Iniciando Paso 3: Filtros de Calidad y Formato")
    
    final_output = os.path.join(output_base, "03.cleaned")

    pipeline = [
        JsonlReader(input_path),

        GopherRepetitionFilter(
            language="es",
            dup_line_frac=cfg["dup_line_frac"],
            top_n_grams=cfg["top_n_grams"],
            dup_n_grams=cfg["dup_n_grams"],
            exclusion_writer=JsonlWriter(os.path.join(output_base, "03.removed_gopherrep"))
        ),

        FineWebQualityFilter(
            language="es",
            char_duplicates_ratio=cfg["char_duplicates_ratio"],
            line_punct_thr=cfg["line_punct_thr"],
            new_line_ratio=cfg["new_line_ratio"],
            exclusion_writer=JsonlWriter(os.path.join(output_base, "03.removed_fwqlty"))
        ),

        GopherQualityFilter(
            language="es",
            max_avg_word_length=cfg["max_avg_word_length"],
            min_avg_word_length=cfg["min_avg_word_length"],
            stop_words=cfg["stopwords"],
            max_non_alpha_words_ratio=cfg["max_non_alpha_words_ratio"],
            min_stop_words=2,
            exclusion_writer=JsonlWriter(os.path.join(output_base, "03.removed_gopherqual"))
        ),

        FTFYFormatter(),
        PIIFormatter(),
        SymbolLinesFormatter(symbols_to_remove=["|"]),

        JsonlWriter(final_output)
    ]

    LocalPipelineExecutor(
        pipeline=pipeline,
        tasks=tasks,
        logging_dir=os.path.join(output_base, "logs/final")
    ).run()

    return final_output

def main():
    # 1. Argumentos y Configuración
    args = get_args()
    cfg = load_config()

    # 2. Definición de rutas
    input_path, output_path = get_paths(cfg, args.name, args.domain, args.version)
    
    print(f"--- Datatrove Curation Pipeline ---")
    print(f"Corpus: {args.name} | Dominio: {args.domain} | Versión: {args.version}")
    print(f"Entrada: {input_path}")
    print(f"Salida:  {output_path}")
    print(f"Tasks:   {args.tasks}")
    print("-" * 40)

    os.makedirs(output_path, exist_ok=True)

    # 3. Ejecución del Pipeline Secuencial
    
    # Paso 1: Filtro de Idioma
    path_after_lang = step_language_filter(input_path, output_path, cfg, args.tasks)
    
    # Paso 2: Deduplicación
    path_after_dedup = step_deduplication(path_after_lang, output_path, cfg, args.tasks)
    
    # Paso 3: Calidad Final
    step_quality_filter(path_after_dedup, output_path, cfg, args.tasks)
    
    logging.info("\n✅ Pipeline finalizado exitosamente.")

if __name__ == "__main__":
    main()
