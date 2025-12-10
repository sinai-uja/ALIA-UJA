"""
Funciones auxiliares para manejo de archivos y logging
"""
import json
import time
import csv
import threading
from pathlib import Path
from typing import Dict, Any, List

# Lock global para escritura thread-safe
csv_lock = threading.Lock()

def save_failed_item(
    item: Dict[str, Any],
    stage: str,
    error_msg: str,
    paths: Dict[str, Path],
    raw_output: str = ""
) -> None:
    """
    Guarda elementos que fallaron para análisis posterior
    """
    failed_path = paths.get("failed", Path("failed_items.jsonl"))

    with csv_lock:
        with open(failed_path, "a", encoding="utf-8") as f:
            failure_record = {
                "id": item.get('id', 'N/A'),
                "id_chunk": item.get('id_chunk', ''),
                "id_document": item.get('id_document', ''),
                "stage": stage,
                "error": error_msg,
                "raw_output": raw_output[:500] if raw_output else "",
                "passage_preview": item.get('passage', '')[:100],
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            f.write(json.dumps(failure_record, ensure_ascii=False) + "\n")

def initialize_csv_files(paths: Dict[str, Path], headers: Dict[str, List[str]]) -> None:
    """
    Inicializa archivos CSV con headers
    """
    for csv_type in ["types", "selections", "queries"]:
        # Crear directorio si no existe
        paths[csv_type].parent.mkdir(parents=True, exist_ok=True)
        
        with open(paths[csv_type], "w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers[csv_type])
            writer.writeheader()

    # Limpiar archivo de fallidos si existe
    if paths["failed"].exists():
        paths["failed"].unlink()

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
    item_id: int
) -> Dict[str, Any]:
    """
    Prepara prompts para un item del dataset
    """
    passage = row.get("passage", "")
    character = row.get("character", "")
    source_id = row.get("source_id", "")
    id_chunk = row.get("id_chunk", "")
    id_document = row.get("id_document", "")

    if not passage or not character:
        print(f"[WARNING] Saltando ID {item_id}: passage o character vacíos")
        return None

    return {
        "id": item_id,
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
    template_files = {
        "types": config["types_prompt_file"],
        "selection": config["selection_prompt_file"],
        "query": config["query_prompt_file"]
    }

    for name, file_path in template_files.items():
        with open(base_dir / file_path, "r", encoding="utf-8") as f:
            templates[name] = f.read()
    
    return templates
