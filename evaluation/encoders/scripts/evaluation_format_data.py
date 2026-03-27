import os, sys, glob
from pathlib import Path
from typing import Dict, Any, List, Mapping, Tuple

import polars as pl
import logging

sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_config, RichArgumentParser
from utils.utils_alia import load_jsonl, write_jsonl, load_data

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# Config
try:
    config_file = os.path.join(os.path.dirname(__file__), "config.yaml")
    logging.info(f"Cargando configuración desde {config_file}")
    CONFIG = load_config(config_file)
    logging.info("Configuración cargada correctamente.")
except Exception as e:
    logging.exception(f"No se pudo cargar la configuración: {e}")
    raise

def get_args() -> Tuple[List[str], List[str]]:
    parser = RichArgumentParser(description="Formatea resultados JSONL de evaluación a CSV resumen por fichero")
    parser.add_argument("--domain", required=True, type=str, help="Dominio de los resultados a procesar")
    parser.add_argument("--task", required=True, type=str, help="Tarea de los resultados a procesar")
    args = parser.parse_args()
    
    if args.domain == "all":
        logging.info("Procesando todos los dominios disponibles en la configuración.")
        domains = list(CONFIG.get("available-domains", []))
    else:
        domains = [args.domain]
    
    if args.task == "all":
        logging.info("Procesando todas las tareas disponibles en la configuración.")
        tasks = ["Retrieval", "STS"]
    else:
        tasks = [args.task]
    
    logging.info(f"> Dominios a procesar: {domains}")
    logging.info(f"> Tareas a procesar: {tasks}")
    
    return domains, tasks

def _process_triplets(
    df: pl.DataFrame, 
    max_samples: int = 0, 
    source_column: str = "source_id", 
    seed: int = 42
) -> pl.DataFrame:
    
    """Procesa un DataFrame de triplets.
    - Si max_samples es 0 o negativo, devuelve el DataFrame sin cambios.
    - El DataFrame devuelto se limita a max_samples filas si max_samples es positivo y menor que el número total de filas.
    - El muestreo se realiza de forma que haya un número equilibrado de triplets por cada valor único en source_column, si es posible. Si no se puede equilibrar perfectamente, se muestrean aleatoriamente los triplets restantes.
    """
    
    if max_samples <= 0 or df.height <= max_samples:
        logging.info(f"No se aplica limitación de max_samples (max_samples={max_samples}, total registros={df.height})")
        return df
    logging.info(f"Procesando triplets para limitar a max_samples={max_samples} (total registros antes: {df.height})")
    # Contar triplets por cada valor único en source_column
    counts = df.group_by(source_column).len().select([source_column, pl.col("len")])
    # Calcular cuántos triplets se deben seleccionar de cada source_column para equilibrar
    total_count = counts.sum().to_dict(as_series=False)["len"][0]
    if total_count == 0:
        logging.warning("No hay triplets para procesar.")
        return df
    samples_per_source = max_samples // counts.height if counts.height > 0 else 0
    remaining_samples = max_samples - (samples_per_source * counts.height)
    # Seleccionar triplets equilibrados por source_column
    selected_rows = []
    for row in counts.iter_rows():
        source, count = row[0], row[1]
        n_samples = samples_per_source + (1 if remaining_samples > 0 else 0)
        remaining_samples -= 1 if remaining_samples > 0 else 0
        # Seleccionar aleatoriamente n_samples de los triplets con source_column == source
        df_subset = df.filter(pl.col(source_column) == source)
        selected_subset = df_subset.sample(n=min(n_samples, count), seed=seed)
        selected_rows.extend(selected_subset.rows())
    # Crear nuevo DataFrame con las filas seleccionadas
    new_df = pl.DataFrame(selected_rows, schema=df.schema)
    return new_df

def get_triplets(
    orig_path_triplets: str,
    dest_path_triplets: str,
    max_samples: int = 0,
    seed: int = 42,
) -> pl.DataFrame:
    
    """Carga y procesa los triplets desde el JSONL, limitando a max_samples si se indica."""
                
    if os.path.exists(dest_path_triplets):
        logging.info(f"Archivo de triplets procesados ya existe: {dest_path_triplets}. Cargando desde allí.")
        try:
            df = load_jsonl(dest_path_triplets)
            logging.info(f"Triplets procesados cargados correctamente. Total registros: {df.height}")
            return df
        except Exception as e:
            logging.exception(f"Error al cargar los triplets procesados desde {dest_path_triplets}: {e}")
            raise
    
    if not os.path.exists(orig_path_triplets):
        logging.error(f"Archivo de triplets no encontrado: {orig_path_triplets}")
        raise FileNotFoundError(f"Archivo de triplets no encontrado: {orig_path_triplets}")

    try:
        
        logging.info(f"Cargando triplets desde {orig_path_triplets}")
        df = load_jsonl(orig_path_triplets)
        logging.info(f"> Triplets cargados correctamente. Total registros: {df.height}")
        
    except Exception as e:
        logging.exception(f"Error al cargar los triplets desde {orig_path_triplets}: {e}")
        raise

    # Sample a max_samples si se indica y es menor que el total
    logging.info(f"Evaluando necesidad de limitar triplets a max_samples={max_samples} (total registros: {df.height})")
    if (max_samples > 0) and (df.height > max_samples):
        logging.info(f"Limitando triplets a max_samples={max_samples}")
        triplets = _process_triplets(df, max_samples=max_samples, seed=seed)
        logging.info(f"> Triplets limitados a {triplets.height} registros.")
        write_jsonl(triplets, dest_path_triplets)
        logging.info(f"> Triplets procesados guardados en {dest_path_triplets}")
    else:
        logging.info(f"No se aplica limitación de max_samples.")
        dest_path_triplets = dest_path_triplets.replace(str(max_samples), str(df.height))
        write_jsonl(df, dest_path_triplets)
        logging.info(f"> Triplets guardados en {dest_path_triplets} sin cambios.")
        triplets = df
            
    return triplets
    

def process_set(domain: str, task: str):
    
    triplets_path = os.path.join(
        CONFIG['paths']['path-root-data'],
        CONFIG['paths']['path-dir-root-triplets'].format(domain=domain),
        CONFIG['paths']['path-file-root-triplets'].format(domain=domain),
    )
    
    for max_sample in CONFIG['max_samples']:
        
        logging.info(f"🤖 Procesando con max_samples={max_sample}")
        set_name = f"ALIA-{max_sample}-{domain}-{task}"
    
        processed_triplets_path = os.path.join(
            CONFIG['paths']['path-root-data'],
            CONFIG['paths']['path-dir-data'].format(domain=domain),
            f"{set_name}.jsonl"
        )
        
        dataset = get_triplets(
            orig_path_triplets=triplets_path,
            dest_path_triplets=processed_triplets_path,
            max_samples=max_sample,
            seed=CONFIG['Evaluator']['seed']
        )
        
        logging.info(f"Conjunto '{set_name}' procesado. Total triplets: {dataset.height}")
    

def main():
    
    domains, tasks = get_args()
    for domain, task in [ (d, t) for d in domains for t in tasks ]:
        logging.info(f"🎢 Procesando dominio '{domain}' con tarea '{task}'")
        process_set(
            domain=domain, 
            task=task
        )
    
if "__main__" == __name__:
    main()
    logging.info(f"Finalizando módulo {os.path.basename(__file__)}")