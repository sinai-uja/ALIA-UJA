"""
Pipeline de generación de QA con VLLM
"""
import time
import yaml
import sys
from pathlib import Path
from typing import Dict, Any, List
from vllm import LLM, SamplingParams
from vllm.sampling_params import GuidedDecodingParams
import polars as pl

# Imports locales
from models import QuestionTypes, Selection
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
    """Configura rutas de archivos dinámicamente en raw/"""
    try:
        # 1. Obtener nombre limpio del dataset
        dataset_path = Path(config["dataset_path"])
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
    Crea SamplingParams con GuidedDecodingParams
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
        print(f" 🔍 {stage.upper()} BeamSearch: beam_width={beam_width}, temp={temperature}")
        return SamplingParams(
            n=beam_width,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            guided_decoding=guided_decoding_params
        )
    else:
        print(f" 📊 {stage.upper()} Sampling: temp={temperature}, top_p={top_p}")
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
    Procesa un batch completo con temperatura
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

    # === ETAPA 3: QUERIES (+ANSWERS opcional) ===
    print(f"\n{'='*60}")
    generate_answer = config.get("generate_answer", True)
    if generate_answer:
        print("ETAPA 3: GENERACIÓN DE PREGUNTA Y RESPUESTA")
        from models import QueryWithAnswer
        query_schema = QueryWithAnswer
    else:
        print("ETAPA 3: GENERACIÓN DE PREGUNTA (SIN RESPUESTA)")
        from models import QueryOnly
        query_schema = QueryOnly
    print(f"{'='*60}")
    
    query_params = create_sampling_params(config, query_schema, "query")
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

    # === DETECCIÓN DE PROGRESO PREVIO (FILTRADO) ===
    processed_ids = set()
    if paths["queries"].exists():
        print(f"🔍 Comprobando archivo de salida existente: {paths['queries']}")
        try:
            existing_df = pl.read_csv(paths["queries"], infer_schema_length=0)
            
            if "id_chunk" in existing_df.columns:
                processed_ids = set(existing_df["id_chunk"].to_list())
                print(f"✅ Encontrados {len(processed_ids)} IDs ya completados en el CSV.")
            else:
                print("⚠️ El archivo existe pero no tiene la columna 'id_chunk'. Se procesará todo.")
        except Exception as e:
            print(f"⚠️ Error al leer CSV de progreso ({e}). Se intentará procesar todo.")

    # === INICIALIZAR CSVs ===
    if len(processed_ids) > 0:
        print(f"⚠️ MODO CONTINUACIÓN: Se omitirá la inicialización de CSVs para preservar {len(processed_ids)} registros.")
        print("   Los nuevos resultados se añadirán (append) a los archivos existentes.")
    else:
        print("📝 Inicializando archivos CSV (Modo Limpio)...")
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
        total_original = len(df)
        print(f"✅ Dataset cargado: {total_original} filas")
    except Exception as e:
        print(f"❌ ERROR al cargar dataset: {e}")
        sys.exit(1)

    # === FILTRADO DE IDs YA PROCESADOS ===
    if len(processed_ids) > 0:
        print(f"🧹 Filtrando registros ya procesados...")
        df = df.filter(~pl.col("id_chunk").cast(pl.Utf8).is_in(processed_ids))
        
        remaining_rows = len(df)
        print(f"📉 Filtrado completado: {total_original} -> {remaining_rows} filas restantes.")
        if remaining_rows == 0:
            print("✅ Todos los registros ya han sido procesados. Finalizando.")
            sys.exit(0)

    if config.get("limit"):
        df = df.head(config["limit"])
        print(f"⚠️ Limitando a {len(df)} filas por configuración")

    # === PREPARAR ITEMS ===
    print("\n📊 Preparando items restantes...")
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
    
    print(f"✅ Items válidos a procesar: {len(items)}")
    
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
    total_processed_this_run = len(items)
    
    success_count = 0
    if paths["queries"].exists():
        try:
            df = pl.read_csv(paths["queries"])
            success_count = len(df)
            print(f"📊 Registros completados encontrados: {success_count}")
        except Exception as e:
            print(f"⚠️ Error al leer CSV de salida: {e}")
            success_count = 0
            
    print(f"\n{'='*60}")
    print("✅ PIPELINE COMPLETADO")
    print(f"{'='*60}")
    print(f"⏱️ Tiempo total sesión: {elapsed:.2f}s ({elapsed/60:.2f} min)")
    print(f"\n📊 Estadísticas acumuladas:")
    print(f" - Procesados esta sesión: {total_processed_this_run}")
    print(f" - ✅ Total Acertados (Global): {success_count}")
    
    print(f"\n📁 Archivos generados:")
    for name, path in paths.items():
        if path.exists():
            size = path.stat().st_size / (1024*1024)  # MB
            print(f" - {name}: {path} ({size:.2f} MB)")

if __name__ == "__main__":
    main()
