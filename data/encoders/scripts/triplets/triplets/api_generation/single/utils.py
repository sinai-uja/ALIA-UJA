"""
Funciones auxiliares para manejo de archivos y logging
"""
import json
import time
import csv
import threading
import logging
from pathlib import Path
from typing import Dict, Any, List

# Lock global para escritura thread-safe
csv_lock = threading.Lock()

def setup_logger(output_dir: Path, filename: str = "process.log") -> logging.Logger:
    """
    Configura y devuelve un logger que escribe en archivo y consola
    """
    logger = logging.getLogger("qwen_processor")
    
    # Evitar duplicar handlers si se llama varias veces
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # Formato
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 1. File Handler
    log_file = output_dir / filename
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 2. Console Handler (opcional, para ver cosas críticas)
    # console_handler = logging.StreamHandler()
    # console_handler.setFormatter(formatter)
    # logger.addHandler(console_handler)
    
    return logger


def save_failed_item(
    item: Dict[str, Any],
    stage: str,
    error_msg: str,
    paths: Dict[str, Path],
    raw_output: str = "",
    id_column: str = "id_chunk"
) -> None:
    """
    Guarda elementos que fallaron para análisis posterior
    """
    failed_path = paths.get("failed", Path("failed_items.jsonl"))

    with csv_lock:
        with open(failed_path, "a", encoding="utf-8") as f:
            failure_record = {
                "id": item.get('id', 'N/A'),
                id_column: item.get(id_column, item.get('id_chunk', '')),
                "id_document": item.get('id_document', ''),
                "stage": stage,
                "error": error_msg,
                "raw_output": raw_output[:500] if raw_output else "",
                "passage_preview": item.get('passage', '')[:100],
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            f.write(json.dumps(failure_record, ensure_ascii=False) + "\n")

def initialize_csv_file(path: Path, headers: List[str]) -> None:
    """
    Inicializa un archivo CSV con headers si no existe o está vacío
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    if not path.exists() or path.stat().st_size == 0:
        with open(path, "w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()

def initialize_jsonl_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def write_to_jsonl(path: Path, data: Dict[str, Any]) -> None:
    with csv_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            f.flush()

def write_to_csv(
    path: Path,
    headers: List[str],
    data: Dict[str, Any]
) -> None:
    """
    Escribe una fila a CSV con thread-safety
    """
    with csv_lock:
        with open(path, "a", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writerow(data)
            f.flush()

def prepare_prompts(
    row: Dict[str, Any],
    selection_template: str,
    query_template: str,
    item_id: int,
    id_column: str = "id_chunk"
) -> Dict[str, Any]:
    """
    Prepara prompts para un item del dataset
    """
    passage = row.get("passage", "")
    character = row.get("character", "")
    source_id = row.get("source_id", "")
    id_chunk = row.get(id_column, "")
    id_document = row.get("id_document", "")

    if not passage or not character:
        # print(f"[WARNING] Saltando ID {item_id}: passage o character vacíos")
        return None

    return {
        "id": item_id,
        id_column: id_chunk,
        "id_chunk": id_chunk,
        "id_document": id_document,
        "passage": passage,
        "character": character,
        "source_id": source_id,
        "query_template": query_template,
    }

def load_prompt_templates(base_dir: Path, config: Dict[str, Any]) -> Dict[str, str]:
    """
    Carga todos los templates de prompts
    """
    templates = {}
    
    # Determinar qué prompt de query usar según configuración
    generate_answer = config.get("generate_answer", True)
    
    if generate_answer:
        query_prompt_key = "query_answer_prompt_file"
    else:
        query_prompt_key = config.get("query_only_prompt_file") and "query_only_prompt_file" or "query_answer_prompt_file"
    
    template_files = {
        "types": config["types_prompt_file"],
        "selection": config["selection_prompt_file"],
        "query": config[query_prompt_key]
    }

    for name, file_path in template_files.items():
        with open(base_dir / file_path, "r", encoding="utf-8") as f:
            templates[name] = f.read()
    
    return templates
