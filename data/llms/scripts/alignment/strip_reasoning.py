#!/usr/bin/env python3
"""
Elimina filas del dataset DPO donde 'chosen' o 'rejected' contienen
trazas de razonamiento (e.g., 'Thinking Process:').
"""

import json
import re
import sys
from pathlib import Path

# Patrones de inicio de trazas de razonamiento
REASONING_START_PATTERNS = [
    r"Thinking Process:\s*",
    r"Reasoning:\s*",
    r"Razonamiento:\s*",
    r"thinking process:\s*",
    r"reasoning:\s*",
    r"razonamiento:\s*",
]

# Compilar regex que detecta cualquiera de estos patrones al inicio del texto
START_RE = re.compile(
    r"^(?:" + "|".join(REASONING_START_PATTERNS) + r")",
    re.IGNORECASE,
)


def has_reasoning_trace(text: str) -> bool:
    """Devuelve True si el texto contiene una traza de razonamiento al inicio."""
    if not text:
        return False
    return bool(START_RE.match(text))


def process_dataset(input_path: str, output_path: str) -> dict:
    """
    Procesa el dataset JSONL eliminando filas con trazas de razonamiento.
    Retorna estadísticas.
    """
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Error: No se encontró {input_path}")
        sys.exit(1)

    stats = {
        "total": 0,
        "removed": 0,
        "removed_chosen": 0,
        "removed_rejected": 0,
        "removed_both": 0,
        "kept": 0,
    }

    with input_file.open("r", encoding="utf-8") as fin, \
         output_file.open("w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue

            data = json.loads(line)
            stats["total"] += 1

            chosen = data.get("chosen", "")
            rejected = data.get("rejected", "")

            chosen_has_reasoning = has_reasoning_trace(chosen)
            rejected_has_reasoning = has_reasoning_trace(rejected)

            if chosen_has_reasoning or rejected_has_reasoning:
                stats["removed"] += 1
                if chosen_has_reasoning:
                    stats["removed_chosen"] += 1
                if rejected_has_reasoning:
                    stats["removed_rejected"] += 1
                if chosen_has_reasoning and rejected_has_reasoning:
                    stats["removed_both"] += 1
                continue  # Saltar esta fila (no escribirla)

            stats["kept"] += 1
            fout.write(json.dumps(data, ensure_ascii=False) + "\n")

    return stats


def main():
    input_path = "dpo_data/dpo_dataset_clean_merged.jsonl"
    output_path = "dpo_data/dpo_dataset_clean_merged_no_reasoning.jsonl"

    print(f"Procesando: {input_path}")
    stats = process_dataset(input_path, output_path)

    print(f"\n{'='*50}")
    print("ESTADÍSTICAS DE FILTRADO")
    print(f"{'='*50}")
    print(f"Total de ejemplos procesados: {stats['total']}")
    print(f"Ejemplos eliminados: {stats['removed']}")
    print(f"  - Por 'chosen' con razonamiento: {stats['removed_chosen']}")
    print(f"  - Por 'rejected' con razonamiento: {stats['removed_rejected']}")
    print(f"  - Por ambos con razonamiento: {stats['removed_both']}")
    print(f"Ejemplos conservados: {stats['kept']}")
    print(f"\nDataset filtrado guardado en: {output_path}")


if __name__ == "__main__":
    main()
