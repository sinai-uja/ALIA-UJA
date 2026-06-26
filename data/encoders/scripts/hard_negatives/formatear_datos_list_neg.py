import json
import argparse
import os
from collections import defaultdict

def convert_dataset(input_path, output_path, query_field="query", passage_field="passage"):
    """
    Convierte un dataset JSONL agrupando múltiples negativos por query.
    Formato entrada: {query_field, passage_field, negative, ...}
    Formato salida: {messages, positive_messages[[]], negative_messages[[]]}
    """

    if not os.path.exists(input_path):
        print(f"Error: No se encuentra el archivo de entrada: {input_path}")
        return

    print(f"Procesando: {input_path}")
    print(f"Campo query: {query_field} | Campo passage: {passage_field}")

    # Diccionario para agrupar por query
    grouped_data = defaultdict(lambda: {"passage": None, "negatives": []})
    errors = 0

    try:
        # Primera pasada: agrupar por query
        with open(input_path, 'r', encoding='utf-8') as f_in:
            for line_num, line in enumerate(f_in, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)

                    query_text = data.get(query_field, "")
                    passage_text = data.get(passage_field, "")
                    negative_text = data.get("negative", "")

                    if not query_text or not passage_text:
                        print(f"[Aviso] Línea {line_num} ignorada: faltan campos obligatorios.")
                        errors += 1
                        continue

                    if grouped_data[query_text]["passage"] is None:
                        grouped_data[query_text]["passage"] = passage_text

                    if negative_text:
                        grouped_data[query_text]["negatives"].append(negative_text)

                except json.JSONDecodeError:
                    print(f"[Aviso] Línea {line_num} ignorada: JSON inválido.")
                    errors += 1

        # Segunda pasada: escribir formato de salida
        with open(output_path, 'w', encoding='utf-8') as f_out:
            for query_text, content in grouped_data.items():
                new_record = {
                    "messages": [
                        {"role": "user", "content": query_text}
                    ],
                    "positive_messages": [
                        [
                            {"role": "user", "content": content["passage"]}
                        ]
                    ],
                    "negative_messages": [
                        [{"role": "user", "content": neg}] for neg in content["negatives"]
                    ]
                }

                f_out.write(json.dumps(new_record, ensure_ascii=False) + "\n")

        print(f"✓ Queries únicas: {len(grouped_data)}")
        print(f"✓ Archivo guardado en: {output_path}")

    except Exception as e:
        print(f"Error crítico: {e}")


def process_input(input_path, output_path, query_field, passage_field):
    """
    Determina si la entrada es un archivo o una carpeta y procesa.
    """
    if os.path.isfile(input_path):

        if os.path.isdir(output_path) or output_path.endswith('/'):
            os.makedirs(output_path, exist_ok=True)
            output_file = os.path.join(output_path, os.path.basename(input_path))
        else:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            output_file = output_path

        convert_dataset(input_path, output_file, query_field, passage_field)

    elif os.path.isdir(input_path):

        os.makedirs(output_path, exist_ok=True)
        jsonl_files = [f for f in os.listdir(input_path) if f.endswith('.jsonl')]

        for filename in jsonl_files:
            convert_dataset(
                os.path.join(input_path, filename),
                os.path.join(output_path, filename),
                query_field,
                passage_field
            )

    else:
        print(f"Error: {input_path} no es válido.")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Conversor SWIFT con múltiples negativos.")

    parser.add_argument("-i", "--input", required=True,
                        help="Ruta de archivo o carpeta de entrada")
    parser.add_argument("-o", "--output", required=True,
                        help="Ruta de archivo o carpeta de salida")

    parser.add_argument("--query_field", default="query",
                        help="Nombre del campo de query (default: query)")

    parser.add_argument("--passage_field", default="passage",
                        help="Nombre del campo de passage/context (default: passage)")

    args = parser.parse_args()

    process_input(args.input, args.output, args.query_field, args.passage_field)
