"""
Pipeline de generación de QA con AsyncOpenAI client
"""
import time
import yaml
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List
from openai import AsyncOpenAI, OpenAIError
from tqdm import tqdm
import polars as pl
import logging

from models import QuestionTypes, Selection, QueryWithAnswer
from utils import (
    initialize_csv_file,
    prepare_prompts,
    load_prompt_templates,
    setup_logger
)
from generators import (
    generate_types,
    generate_selections,
    generate_queries_with_answers
)


def load_config(config_path: Path) -> Dict[str, Any]:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ ERROR Config: {e}")
        sys.exit(1)


def setup_paths(config: Dict[str, Any], override_output_dir: Path = None) -> Dict[str, Path]:
    try:
        dataset_path = Path(config["dataset_path"])
        dataset_name = dataset_path.stem.replace("_with_persona", "")

        if override_output_dir:
            output_dir = override_output_dir / dataset_name
        else:
            output_dir = Path("raw_qwen") / dataset_name
            
        output_dir.mkdir(parents=True, exist_ok=True)
        # print(f"📂 Directorio de salida: {output_dir}")

        paths = {
            "root": output_dir,
            "failed": output_dir / "failed_items.jsonl"
        }
        
        save_csv = config.get("save_csv", True)
        save_jsonl = config.get("save_jsonl", True)
        
        if save_csv:
            paths["types"] = output_dir / f"{config['types_output_name']}.csv"
            paths["selections"] = output_dir / f"{config['selection_output_name']}.csv"
            paths["queries"] = output_dir / f"{config['query_output_name']}.csv"
            
        if save_jsonl:
            paths["types_jsonl"] = output_dir / f"{config['types_output_name']}.jsonl"
            paths["selections_jsonl"] = output_dir / f"{config['selection_output_name']}.jsonl"
            paths["queries_jsonl"] = output_dir / f"{config['query_output_name']}.jsonl"
            
        return paths
    except KeyError as e:
        print(f"❌ ERROR Path Setup: {e}")
        sys.exit(1)


def setup_headers(config: Dict[str, Any]) -> Dict[str, List[str]]:
    id_col = config.get("id_column", "id_chunk")
    return {
        "types": [id_col, "id_document", "passage", "character", "types", "model", "source_id"],
        "selections": [id_col, "id_passage_query", "id_document", "passage", "character", "selected_character", "question_type", "difficulty", "selection_model", "source_id"],
        "queries": [id_col, "id_passage_query", "id_document", "passage", "character", "type", "difficulty", "query", "answer", "query_model", "source_id"]
    }


async def process_batch_pipeline(
    batch: List[Dict[str, Any]],
    client: AsyncOpenAI,
    templates: Dict[str, str],
    paths: Dict[str, Path],
    headers: Dict[str, List[str]],
    config: Dict[str, Any]
) -> None:
    """Procesa un batch completo esperando cada etapa"""
    model_name = config["model"]
    max_retries = config.get("max_retries", 3)
    
    await generate_types(
        batch, client, templates["types"], paths, headers["types"], model_name, config, max_retries
    )
    
    await generate_selections(
        batch, client, templates["selection"], paths, headers["selections"], model_name, config, max_retries
    )
    
    await generate_queries_with_answers(
        batch, client, templates["query"], paths, headers["queries"], model_name, config, max_retries
    )


async def run_pipeline(
    config: Dict[str, Any],
    dataset_path_override: Path = None,
    output_dir_override: Path = None
):
    """Lógica principal del pipeline desacoplada de args"""
    start_time_total = time.time()
    
    # 1. Configuración de rutas
    if dataset_path_override:
        config["dataset_path"] = str(dataset_path_override)
        
    paths = setup_paths(config, override_output_dir=output_dir_override)
    headers = setup_headers(config)
    
    # 2. Configurar Logger (en el directorio de salida)
    logger = setup_logger(paths["root"], "process.log")
    
    dpath = Path(config["dataset_path"])
    logger.info(f"START PIPELINE | Dataset: {dpath.name}")
    
    base_dir = Path(__file__).parent
    templates = load_prompt_templates(base_dir, config)

    # 3. Cliente Async
    client = AsyncOpenAI(
        base_url=config.get("api_base_url"),
        api_key=config.get("api_key", "EMPTY"),
    )

    # 4. Cargar Dataset
    if not dpath.exists():
        msg = f"❌ Dataset no encontrado: {dpath}"
        print(msg)
        logger.error(msg)
        return

    df = pl.read_parquet(dpath)
    
    # 5. Filtrar ya procesados
    processed_ids = set()
    query_csv = paths.get("queries")
    query_jsonl = paths.get("queries_jsonl")
    
    if (query_csv and query_csv.exists()) or (query_jsonl and query_jsonl.exists()):
        try:
            id_col = config.get("id_column", "id_chunk")
            if query_csv and query_csv.exists():
                existing_df = pl.read_csv(query_csv, infer_schema_length=0)
                if id_col in existing_df.columns:
                    processed_ids = set(existing_df[id_col].to_list())
            elif query_jsonl and query_jsonl.exists():
                existing_df = pl.read_ndjson(query_jsonl)
                if id_col in existing_df.columns:
                    processed_ids = set(existing_df[id_col].to_list())
            
            if processed_ids:
                logger.info(f"Resuming | Found {len(processed_ids)} processed items")
        except Exception:
            pass

    if config.get("limit"):
        df = df.head(config["limit"])
        logger.info(f"LIMIT applied: {config['limit']} items")

    if len(processed_ids) > 0:
        id_col = config.get("id_column", "id_chunk")
        df = df.filter(~pl.col(id_col).cast(pl.Utf8).is_in(processed_ids))

    if len(df) == 0:
        msg = f"✅ {dpath.name}: Todo procesado."
        print(msg)
        logger.info(msg + " NO ACTION")
        return

    print(f"📊 Procesando: {dpath.name} | Items: {len(df)}")
    logger.info(f"Processing {len(df)} items")

    # 6. Inicializar CSVs si es necesario
    from utils import initialize_jsonl_file
    for csv_type in ["types", "selections", "queries"]:
        if csv_type in paths and csv_type in headers:
            initialize_csv_file(paths[csv_type], headers[csv_type])
        jsonl_key = f"{csv_type}_jsonl"
        if jsonl_key in paths:
            initialize_jsonl_file(paths[jsonl_key])

    # Limpiar archivo de fallidos si es una ejecución nueva (opcional, aquí lo dejamos igual)
    # paths["failed"].unlink(missing_ok=True)

    # 7. Preparar items
    items = []
    for idx, row in enumerate(df.iter_rows(named=True)):
        item = prepare_prompts(row, templates["selection"], templates["query"], idx, id_column=config.get("id_column", "id_chunk"))
        if item: items.append(item)

    # 8. Procesar
    batch_size = config.get("batch_size", 50)
    total_items = len(items)
    
    # Barra de progreso principal para ITEMS
    pbar = tqdm(total=total_items, desc="Progreso Global", unit="items")
    
    api_max_attempts = config.get("api_max_attempts", 6)
    api_retry_delay = config.get("api_retry_delay", 600)

    for i in range(0, total_items, batch_size):
        batch_start_time = time.time()
        batch = items[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        
        attempts = 0
        success = False
        while attempts < api_max_attempts:
            try:
                # Procesar batch
                await process_batch_pipeline(batch, client, templates, paths, headers, config)
                success = True
                break
            except OpenAIError as e:
                attempts += 1
                logger.error(f"Batch {batch_num} API Error: {e}")
                if attempts >= api_max_attempts:
                    msg = f"❌ Batch {batch_num} FAILED after {api_max_attempts} attempts. STOPPING PIPELINE."
                    logger.critical(msg)
                    print(f"\n{msg}")
                    pbar.close()
                    return # Corta todo
                
                wait_time = api_retry_delay
                msg = f"⚠️ API Error in batch {batch_num}. Waiting {wait_time/60:.1f} min before attempt {attempts+1}/{api_max_attempts}..."
                logger.warning(msg)
                print(f"\n{msg}")
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Batch {batch_num} UNEXPECTED ERROR: {e}")
                import traceback
                logger.error(traceback.format_exc())
                break # Skip batch or let it continue depending on criticality.

        if not success:
            logger.error(f"Batch {batch_num} skipped due to non-retryable error.")
            continue

        # Stats del batch
        batch_duration = time.time() - batch_start_time
        items_processed = len(batch)
        items_per_sec_batch = items_processed / batch_duration if batch_duration > 0 else 0
        
        # Log del batch
        logger.info(
            f"Batch {batch_num} DONE | Items: {items_processed} | "
            f"Time: {batch_duration:.2f}s | Speed: {items_per_sec_batch:.2f} it/s"
        )
        
        # Actualizar barra global
        pbar.update(items_processed)
        
    pbar.close()

    # === METRICAS FINALES ===
    elapsed_total = time.time() - start_time_total
    avg_per_item = elapsed_total / total_items if total_items > 0 else 0
    items_per_sec = total_items / elapsed_total if elapsed_total > 0 else 0

    end_msg = (
        f"FINISHED {dpath.name}\n"
        f"Time: {elapsed_total:.2f}s ({elapsed_total/60:.2f} min)\n"
        f"Speed: {items_per_sec:.2f} it/s\n"
        f"Avg: {avg_per_item:.2f} s/it"
    )
    
    print(f"\n{end_msg}")
    logger.info(end_msg.replace('\n', ' | '))
    print(f"{'='*60}\n")


async def main_async():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dataset-path", help="Override dataset path")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    dpath = Path(args.dataset_path) if args.dataset_path else None
    
    await run_pipeline(config, dataset_path_override=dpath)


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n👋 Cancelado por usuario.")
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        import traceback
        traceback.print_exc()
