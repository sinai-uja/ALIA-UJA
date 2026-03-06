"""Script de conversión a Parquet para corpus biomédico "Miscelánea".

Este módulo procesa en paralelo múltiples archivos de texto plano (.txt)
correspondientes al corpus biomédico Miscelánea, para consolidarlos en 
un archivo de salida `.parquet`. Utiliza chunking para fragmentar textos
muy extensos y la librería `pyarrow` para la estructuración eficiente.

Example:
    Ejecución básica::

        python parquet_Miscelanea_Roberta.py

    Buscará todos los txt en la ruta por defecto y generará `output.parquet`.

Attributes:
    folder_path (str): Ruta predeterminada de entrada con archivos txt.
    output_path (str): Ruta completa para el archivo parquet de destino.
    CHUNK_SIZE (int): Tamaño de fragmentación por caracteres.

Note:
    Aplica detección de codificación de caracteres mediante `chardet`.
    Soporta procesamiento concurrente para múltiples archivos empleando
    `ProcessPoolExecutor`.
"""

import os
import pandas as pd
import chardet
from concurrent.futures import ProcessPoolExecutor, as_completed
import pyarrow as pa
import pyarrow.parquet as pq

# 📂 Paths
folder_path = r"/mnt/beegfs/alia-data/alia/data/llms/data/interim/biomedical/Miscelanea/docs"
output_path = r"/mnt/beegfs/alia-data/alia/data/llms/data/interim/biomedical/Miscelanea/output.parquet"

# 🔎 Buscar archivos .txt
txt_files = [f for f in os.listdir(folder_path) if f.endswith(".txt")]
total_files = len(txt_files)

# 🔧 Parámetros
CHUNK_SIZE = 500_000  # caracteres por celda máx. (ajústalo si quieres más o menos filas)


def process_file(file_path: str, file_id: int, total: int, chunk_size: int = CHUNK_SIZE) -> list:
    """Procesa y divide un archivo de texto en fragmentos (chunks).

    Abre un archivo .txt dado, detecta automáticamente su codificación
    con base en una muestra grande (5MB), lee su contenido y lo divide 
    en segmentos según `chunk_size`. Cada resultado es mapeado para el schema Parquet.

    Args:
        file_path (str): Ruta local del archivo .txt a procesar.
        file_id (int): Identificador numérico secuencial del archivo procesado.
        total (int): Cantidad total aproximada de archivos a procesar (para logs de progreso).
        chunk_size (int, optional): Tamaño de fragmentación por caracteres. Defaults to CHUNK_SIZE.

    Returns:
        list: Lista de diccionarios con la forma 
            `{"text": str, "dataset": str, "id": str}`
            los cuales representan a las diversas partes del texto segmentado.
    """
    filename = os.path.basename(file_path)
    try:
        print(f"[{file_id+1}/{total}] Iniciando {filename}...")

        # Detectar encoding con una muestra
        with open(file_path, "rb") as f:
            raw_sample = f.read(5 * 1024 * 1024)  # 5 MB
        enc = chardet.detect(raw_sample)["encoding"] or "utf-8"

        rows = []
        with open(file_path, "r", encoding=enc, errors="replace") as f:
            text = f.read()

            # Dividir en chunks
            for idx, start in enumerate(range(0, len(text), chunk_size)):
                chunk = text[start:start+chunk_size]
                rows.append({
                    "text": chunk,
                    "dataset": os.path.splitext(filename)[0],
                    "id": f"{file_id}_{idx}"  # id único por chunk
                })

        print(f"[{file_id+1}/{total}] {filename} completado ✓ ({len(rows)} chunks)")
        return rows

    except Exception as e:
        print(f"[{file_id+1}/{total}] Error procesando {filename}: {e}")
        return []


if __name__ == "__main__":
    # ✍️ Definir schema para Parquet
    schema = pa.schema([
        ("text", pa.string()),
        ("dataset", pa.string()),
        ("id", pa.string())  # ahora id es string, ya que usamos fileID_chunkID
    ])

    # 🚀 Escritura incremental
    with pq.ParquetWriter(output_path, schema, compression="snappy") as writer:
        with ProcessPoolExecutor(max_workers=16) as executor:
            futures = {
                executor.submit(process_file, os.path.join(folder_path, f), i, total_files): f
                for i, f in enumerate(txt_files)
            }

            for future in as_completed(futures):
                results = future.result()
                if results:
                    df_temp = pd.DataFrame(results)
                    table = pa.Table.from_pandas(df_temp, schema=schema)
                    writer.write_table(table)

    print(f"\n✅ Archivo Parquet creado en: {output_path}")
