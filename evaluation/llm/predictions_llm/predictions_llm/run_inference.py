import argparse
import os
import pandas as pd
import torch

from llm_eval.backends import VLLMBackend, TransformersBackend
from llm_eval.checkpoint import init_csv, resume_csv, append_row
from llm_eval.utils import build_prompt, print_progress


def parse_args():
    parser = argparse.ArgumentParser(description="Pipeline generico de inferencia LLM.")
    parser.add_argument("--model_path", required=True, help="Ruta al modelo.")
    parser.add_argument("--input_file", required=True, help="Ruta al dataset (CSV o JSONL).")
    parser.add_argument("--prompt_file", required=True, help="Ruta al archivo de prompt (.txt).")
    parser.add_argument("--output_csv", required=True, help="Ruta al CSV de salida.")
    parser.add_argument("--backend", choices=["vllm", "transformers"], default="transformers",
                        help="Backend de inferencia.")
    parser.add_argument("--batch_size", type=int, default=1, help="Tamano del batch.")
    parser.add_argument("--max_new_tokens", type=int, default=400, help="Maximos tokens a generar.")
    parser.add_argument("--tensor_parallel_size", type=int, default=1,
                        help="(vLLM solo) GPUs para tensor parallelism.")
    parser.add_argument("--stop_sequences", type=str, default="",
                        help="Secuencias de parada separadas por '|'.")
    parser.add_argument("--input_col", type=str, default="input",
                        help="Nombre de la columna de entrada.")
    parser.add_argument("--expected_col", type=str, default="expected_output",
                        help="Nombre de la columna de salida esperada.")
    parser.add_argument("--num_examples", type=int, default=None,
                        help="Numero maximo de ejemplos a procesar (para pruebas).")
    return parser.parse_args()


def load_dataset(path: str, input_col: str, expected_col: str) -> pd.DataFrame:
    """Carga CSV o JSONL y normaliza columnas."""
    if path.endswith(".jsonl"):
        df = pd.read_json(path, lines=True)
    else:
        df = pd.read_csv(path)

    # Renombrar columnas si es necesario
    rename_map = {}
    if input_col != "input" and input_col in df.columns:
        rename_map[input_col] = "input"
    if expected_col != "expected_output" and expected_col in df.columns:
        rename_map[expected_col] = "expected_output"
    if rename_map:
        df = df.rename(columns=rename_map)

    # Asegurar que existen las columnas necesarias
    for col in ["input", "expected_output"]:
        if col not in df.columns:
            raise ValueError(f"Columna '{col}' no encontrada en el dataset. Columnas disponibles: {list(df.columns)}")

    return df[["input", "expected_output"]].reset_index(drop=True)


def main():
    args = parse_args()

    # Leer prompt
    with open(args.prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read().strip()

    # Cargar dataset
    print(f"Cargando dataset desde {args.input_file}...")
    df = load_dataset(args.input_file, args.input_col, args.expected_col)
    print(f"  {len(df)} ejemplos cargados.")

    if args.num_examples is not None:
        df = df.head(args.num_examples)
        print(f"  Limitado a {len(df)} ejemplos para prueba.")

    total = len(df)
    os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)

    # Checkpoint
    start_idx = resume_csv(args.output_csv)
    if start_idx == -1:
        print(f"  CSV completo encontrado. Nada que hacer.")
        return
    elif start_idx == 0:
        init_csv(args.output_csv, df)
        print(f"  {total} ejemplos a procesar. Guardando en: {args.output_csv}\n")
    else:
        print(f"  Checkpoint encontrado: {start_idx}/{total} respuestas ya generadas. Reanudando...\n")

    # Preparar backend
    stop_sequences = [s for s in args.stop_sequences.split("|") if s] if args.stop_sequences else []

    backend_kwargs = {
        "max_new_tokens": args.max_new_tokens,
        "stop_sequences": stop_sequences,
    }
    if args.backend == "vllm":
        backend_kwargs["tensor_parallel_size"] = args.tensor_parallel_size
        backend = VLLMBackend(args.model_path, **backend_kwargs)
    else:
        backend = TransformersBackend(args.model_path, **backend_kwargs)

    backend.load()

    # Bucle de inferencia
    for batch_start in range(start_idx, total, args.batch_size):
        batch_end = min(batch_start + args.batch_size, total)

        prompts = []
        for i in range(batch_start, batch_end):
            question = str(df.at[i, "input"]).strip()
            prompt = build_prompt(backend.tokenizer, prompt_text, question)
            prompts.append(prompt)

        answers = backend.generate(prompts)

        for offset, answer in enumerate(answers):
            i = batch_start + offset
            idx = i + 1
            append_row(args.output_csv, {
                "input": df.at[i, "input"],
                "expected_output": df.at[i, "expected_output"],
                "actual_output": answer,
            })
            print_progress(idx, total, answer)

    print(f"\nResultados guardados en: {args.output_csv}")

    # Limpieza
    del backend
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
