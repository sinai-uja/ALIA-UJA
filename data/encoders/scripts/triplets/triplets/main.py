"""
Pipeline de generación de QA con VLLM
"""
import json
import time
import yaml
import sys
from pathlib import Path
from typing import Dict, Any, List
from vllm import LLM, SamplingParams
from vllm.sampling_params import GuidedDecodingParams
import polars as pl

# Imports locales
from models import QuestionTypes, Selection, QueryWithAnswer
from utils import (
    initialize_csv_files,
    prepare_prompts,
    load_prompt_templates
)
from generators import (
    generate_types,
    generate_selections,
    generate_queries_with_answers
)

def load_config(config_path: Path) -> Dict[str, Any]:
    """Carga configuración desde YAML"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"❌ ERROR: No se encontró el archivo de configuración: {config_path}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ ERROR: El archivo YAML es inválido: {e}")
        sys.exit(1)

def setup_paths(config: Dict[str, Any]) -> Dict[str, Path]:
    """Configura rutas de archivos dinámicamente en raw/<DATASET>/"""
    try:
        # 1. Obtener nombre limpio del dataset
        dataset_path = Path(config["dataset_path"])
        # Elimina '_with_persona' si existe y quita la extensión
        dataset_name = dataset_path.stem.replace("_with_persona", "")
        
        # 2. Definir directorio de salida
        output_dir = Path("raw") / dataset_name
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"📂 Directorio de salida configurado: {output_dir}")

        return {
            "types": output_dir / config["types_output_file"],
            "selections": output_dir / config["selection_output_file"],
            "queries": output_dir / config["query_output_file"],
            "failed": output_dir / "failed_items.jsonl"
        }
    except KeyError as e:
        print(f"❌ ERROR: Falta configuración requerida: {e}")
        sys.exit(1)

def setup_headers() -> Dict[str, List[str]]:
    """Define headers de CSVs"""
    return {
        "types": [
            "id_chunk", "id_document", "passage", "character",
            "types", "model", "source_id"
        ],
        "selections": [
            "id_chunk", "id_document", "passage", "character",
            "selected_character", "question_type", "difficulty",
            "selection_model", "source_id"
        ],
        "queries": [
            "id_chunk", "id_document", "passage", "character",
            "type", "difficulty", "query", "answer", "query_model", "source_id"
        ]
    }

def create_sampling_params(
    config: Dict[str, Any],
    schema,
    stage: str
) -> SamplingParams:
    """
    Crea SamplingParams con GuidedDecodingParams y beam search opcional
    """
    temperature = config.get(f"{stage}_temperature", 0.7)
    top_p = config.get(f"{stage}_top_p", 0.9)
    max_tokens = config.get(f"{stage}_max_tokens", 512)
    use_beam_search = config.get(f"{stage}_use_beam_search", False)
    beam_width = config.get(f"{stage}_beam_width", 1)

    # Crear GuidedDecodingParams con JSON schema
    guided_decoding_params = None
    if schema:
        guided_decoding_params = GuidedDecodingParams(
            json=schema.model_json_schema()
        )

    if use_beam_search and beam_width > 1:
        print(f"   🔍 {stage.upper()} BeamSearch: beam_width={beam_width}, temp={temperature}")
        return SamplingParams(
            n=beam_width,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            guided_decoding=guided_decoding_params
        )
    else:
        print(f"   📊 {stage.upper()} Sampling: temp={temperature}, top_p={top_p}")
        return SamplingParams(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            guided_decoding=guided_decoding_params
        )

def process_batch_pipeline(
    batch: List[Dict[str, Any]],
    llm: LLM,
    templates: Dict[str, str],
    paths: Dict[str, Path],
    headers: Dict[str, List[str]],
    config: Dict[str, Any]
) -> None:
    """
    Procesa un batch completo con temperatura y beam search
    """
    model_name = config["model"]
    max_retries = config.get("max_retries", 3)

    print(f"\n{'='*60}")
    print(f"PROCESANDO BATCH DE {len(batch)} ITEMS")
    print(f"{'='*60}\n")

    # === ETAPA 1: TYPES ===
    print(f"\n{'='*60}")
    print("ETAPA 1: GENERACIÓN DE TIPOS")
    print(f"{'='*60}")
    types_params = create_sampling_params(config, QuestionTypes, "types")
    batch = generate_types(
        batch=batch,
        llm=llm,
        sampling_params=types_params,
        types_template=templates["types"],
        paths=paths,
        types_headers=headers["types"],
        model=model_name,
        config=config,
        max_retries=max_retries,
        timeout_seconds=config.get("types_timeout", 180)
    )

    # === ETAPA 2: SELECTIONS ===
    print(f"\n{'='*60}")
    print("ETAPA 2: SELECCIÓN DE PERSONAJE Y TIPO")
    print(f"{'='*60}")
    selection_params = create_sampling_params(config, Selection, "selection")
    batch = generate_selections(
        batch=batch,
        llm=llm,
        sampling_params=selection_params,
        selection_template=templates["selection"],
        paths=paths,
        selection_headers=headers["selections"],
        model=model_name,
        max_retries=max_retries,
        timeout_seconds=config.get("selection_timeout", 180)
    )

    # === ETAPA 3: QUERIES + ANSWERS ===
    print(f"\n{'='*60}")
    print("ETAPA 3: GENERACIÓN DE PREGUNTA Y RESPUESTA")
    print(f"{'='*60}")
    query_params = create_sampling_params(config, QueryWithAnswer, "query")
    batch = generate_queries_with_answers(
        batch=batch,
        llm=llm,
        sampling_params=query_params,
        query_template=templates["query"],
        paths=paths,
        query_headers=headers["queries"],
        model=model_name,
        config=config,
        max_retries=max_retries,
        timeout_seconds=config.get("query_timeout", 180)
    )

    print(f"\n{'='*60}")
    print("BATCH COMPLETADO")
    print(f"{'='*60}\n")

def main():
    """Función principal con manejo robusto de errores"""
    start_time = time.time()

    # === CONFIGURACIÓN ===
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yaml"
    
    print(f"📋 Cargando configuración desde: {config_path}")
    config = load_config(config_path)
    paths = setup_paths(config)
    headers = setup_headers()

    try:
        templates = load_prompt_templates(base_dir, config)
    except Exception as e:
        print(f"❌ ERROR al cargar templates de prompts: {e}")
        sys.exit(1)

    # === INICIALIZAR CSVs ===
    print("📝 Inicializando archivos CSV...")
    try:
        initialize_csv_files(paths, headers)
    except Exception as e:
        print(f"❌ ERROR al inicializar archivos CSV: {e}")
        sys.exit(1)

    # === CARGAR MODELO ===
    print(f"\n🚀 Cargando modelo: {config['model']}")
    try:
        llm = LLM(
            model=config["model"],
            tensor_parallel_size=config.get("tensor_parallel_size", 1),
            gpu_memory_utilization=config.get("gpu_memory_utilization", 0.9),
            max_model_len=config.get("max_model_len", 4096),
            seed=config.get("seed", 42),
            trust_remote_code=True,
            disable_custom_all_reduce=True,
            max_num_seqs=config.get("batch_size", 256),
            enforce_eager=False,
            distributed_executor_backend="mp"
        )
        print("✅ Modelo cargado correctamente\n")
    except Exception as e:
        print(f"❌ ERROR al cargar modelo: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # === CARGAR DATASET ===
    dataset_path = Path(config["dataset_path"])
    if not dataset_path.exists():
        print(f"❌ ERROR: No se encontró el dataset: {dataset_path}")
        sys.exit(1)

    print(f"📂 Cargando dataset: {dataset_path}")
    try:
        df = pl.read_parquet(dataset_path)
        total_rows = len(df)
        print(f"✅ Dataset cargado: {total_rows} filas")
    except Exception as e:
        print(f"❌ ERROR al cargar dataset: {e}")
        sys.exit(1)

    if config.get("limit"):
        df = df.head(config["limit"])
        print(f"⚠️ Limitando a {len(df)} filas")

    # === PREPARAR ITEMS ===
    print("\n📊 Preparando items...")
    items = []
    for idx, row in enumerate(df.iter_rows(named=True)):
        item = prepare_prompts(
            row=row,
            selection_template=templates["selection"],
            query_template=templates["query"],
            item_id=idx
        )
        if item:
            items.append(item)

    print(f"✅ Items válidos: {len(items)}")
    if len(items) == 0:
        print("❌ ERROR: No hay items válidos para procesar")
        sys.exit(1)

    # === PROCESAMIENTO POR BATCHES ===
    batch_size = config.get("batch_size", 10)
    total_batches = (len(items) + batch_size - 1) // batch_size

    print(f"\n🔄 Procesando {total_batches} batches de {batch_size} items")
    print(f"🔍 Beam search activado en TODAS las etapas")

    try:
        for batch_idx in range(0, len(items), batch_size):
            batch = items[batch_idx:batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1
            
            print(f"\n{'#'*60}")
            print(f"BATCH {batch_num}/{total_batches}")
            print(f"{'#'*60}")

            process_batch_pipeline(
                batch=batch,
                llm=llm,
                templates=templates,
                paths=paths,
                headers=headers,
                config=config
            )

    except KeyboardInterrupt:
        print("\n⚠️ Proceso interrumpido por el usuario")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERROR durante el procesamiento: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # === RESUMEN FINAL ===
    elapsed = time.time() - start_time
    
    total_items = len(items)
    
    # Contamos los éxitos reales leyendo el CSV final generado
    success_count = 0
    if paths["queries"].exists():
        try:
            with open(paths["queries"], 'r', encoding='utf-8') as f:
                # Restamos 1 por el header (si el archivo tiene más de 1 línea)
                line_count = sum(1 for _ in f)
                success_count = max(0, line_count - 1) 
        except Exception:
            success_count = 0
            
    # Los fallidos son simplemente el resto
    failed_count = total_items - success_count
    
    # Estadísticas
    if total_items > 0:
        success_rate = (success_count / total_items) * 100
        failure_rate = (failed_count / total_items) * 100
    else:
        success_rate = 0.0
        failure_rate = 0.0

    print(f"\n{'='*60}")
    print("✅ PIPELINE COMPLETADO")
    print(f"{'='*60}")
    
    print(f"⏱️ Tiempo total: {elapsed:.2f}s ({elapsed/60:.2f} min)")
    
    print(f"\n📊 Estadísticas finales:")
    print(f" - Total items procesados: {total_items}")
    print(f" - ✅ Acertados (Finalizados): {success_count} ({success_rate:.2f}%)")
    print(f" - ❌ Fallados (Incompletos):  {failed_count} ({failure_rate:.2f}%)")

    print(f"\n📁 Archivos generados:")
    for name, path in paths.items():
        if path.exists():
            size = path.stat().st_size / (1024*1024)  # MB
            print(f" - {name}: {path} ({size:.2f} MB)")

if __name__ == "__main__":
    main()
