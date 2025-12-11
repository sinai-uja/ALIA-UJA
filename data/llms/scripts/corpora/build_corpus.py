import polars as pl
import os
import json
import sys
import argparse
import re
import logging
from tqdm import tqdm

# Configuración de logging
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
try:
    from utils.utils_alia import load_config
except ImportError:
    # Fallback por si se ejecuta fuera de la estructura exacta para pruebas
    import yaml
    def load_config(path):
        with open(path, 'r') as f:
            return yaml.safe_load(f)

def get_args():
    """Captura los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Script de procesamiento de Corpus")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    return parser.parse_args()

def get_paths(config, name: str, domain: str, version: int):
    """Centraliza la lógica de generación de rutas para evitar condicionales repetidos."""
    
    parts_path_dir = config['root-data'].format(domain=domain)
    
    if version == -1:
        base_corpus_dir = os.path.join(
            config['root-corpora'], 
            config['path-corpus-dir'].format(domain=domain, name=name)
        )
        info_filename = config['path-info'].format(name=name)
        raw_parquet_filename = config['build']['path-corpus-initial-parquet'].format(name=name)
        clean_parquet_filename = config['build']['path-corpus-cleaned-parquet'].format(name=name)
    else:
        base_corpus_dir = os.path.join(
            config['root-corpora'], 
            config['path-corpus-dir-version'].format(name=name, domain=domain, version=version)
        )
        info_filename = config['path-info-version'].format(name=name, version=version)
        raw_parquet_filename = config['build']['path-corpus-initial-parquet-version'].format(name=name, version=version)
        clean_parquet_filename = config['build']['path-corpus-cleaned-parquet-version'].format(name=name, version=version)

    return {
        "parts_dir": parts_path_dir,
        "corpus_dir": base_corpus_dir,
        "info_json": os.path.join(base_corpus_dir, info_filename),
        "raw_parquet": os.path.join(base_corpus_dir, raw_parquet_filename),
        "clean_parquet": os.path.join(base_corpus_dir, clean_parquet_filename),
        "jsonl_out_dir": os.path.join(base_corpus_dir, config['build']['parts-path-dir-jsonl']),
        "parquet_out_dir": os.path.join(base_corpus_dir, config['build']['parts-path-dir-parquet'])
    }

def clean_text_logic(texto: str) -> str:
    """Aplica las reglas regex al string de entrada."""
    if not isinstance(texto, str):
        return texto

    REGEX_INTERNAL_CR = r"(?<![\.\?\!\:\-])\n(?!\s*[\(\d A-Z])"
    REGEX_NORMALIZAR_SALTOS = r"(\r?\n[\t ]*){3,}"
    REGEX_CLEAN_SPACES_AROUND_CR = r"([\t ]+\n|\n[\t ]+)"
    REGEX_SOLO_NUMERO = r"^\s*\d+(\.\d+)?\s*(\r?\n){1,2}"

    texto = re.sub(REGEX_INTERNAL_CR, " ", texto)
    texto = re.sub(REGEX_NORMALIZAR_SALTOS, "\n", texto)
    texto = re.sub(REGEX_CLEAN_SPACES_AROUND_CR, "\n", texto)
    texto = re.sub(REGEX_SOLO_NUMERO, "", texto)

    return texto

def build_raw_corpus(paths, name):
    """Genera la primera versión del corpus uniendo datasets."""
    if os.path.exists(paths['raw_parquet']):
        logging.info(f"El corpus raw '{name}' ya existe. Saltando paso.")
        return

    logging.info('-'*30 + ' GENERAR PRIMERA VERSIÓN ' + '-'*30)
    
    if not os.path.exists(paths['info_json']):
        logging.error(f"No se encuentra el archivo de información: {paths['info_json']}")
        sys.exit(1)

    corpus_info = json.load(open(paths['info_json'], "r"))
    os.makedirs(paths['corpus_dir'], exist_ok=True)

    logging.info(f"Construyendo corpus '{name}' con {len(corpus_info['datasets'])} datasets...")

    lazy_frames = []
    
    for d in tqdm(corpus_info['datasets'], desc="Escaneando datasets"):
        parquet_path = os.path.join(paths['parts_dir'], d, "dataset.parquet")
        
        if os.path.exists(parquet_path):
            lf = (
                pl.scan_parquet(parquet_path)
                .select([
                    pl.col('id').cast(pl.Utf8),
                    pl.col('text').cast(pl.Utf8)
                ])
                .with_columns(pl.lit(d).alias("source_id"))
            )
            lazy_frames.append(lf)
        else:
            logging.warning(f"⚠️ No se encontró parquet para {d}")

    if lazy_frames:
        # Usamos sink_parquet para streaming (eficiente en memoria)
        pl.concat(lazy_frames).sink_parquet(paths['raw_parquet'])
        try: os.chmod(paths['raw_parquet'], 0o777)
        except Exception as e: pass
        logging.info(f"✅ Corpus guardado en: {paths['raw_parquet']}")
    else:
        logging.error("No se encontraron datasets válidos para concatenar.")

def process_cleaning(paths, config, name):
    """Limpia el texto del corpus."""
    if os.path.exists(paths['clean_parquet']):
        logging.info(f"El corpus limpio '{name}' ya existe. Saltando paso.")
        return

    logging.info('-'*30 + ' LIMPIAR EL TEXTO ' + '-'*30)
    
    text_col = "text"  # Asumimos que la columna de texto se llama 'text'
    
    try:
        # Leemos lazy para optimizar memoria antes de procesar
        # Nota: map_elements forzará la materialización en memoria del chunk que procese
        df = pl.read_parquet(paths['raw_parquet'])
        
        logging.info(f"Aplicando limpieza regex a {len(df)} filas...")
        
        # Aplicamos la limpieza. 
        # return_dtype=pl.Utf8 es importante para la inferencia de tipos de Polars
        df_clean = df.with_columns(
            pl.col(text_col)
            .map_elements(clean_text_logic, return_dtype=pl.Utf8)
            .alias(text_col)
        )
        
        df_clean.write_parquet(paths['clean_parquet'])
        try: os.chmod(paths['clean_parquet'], 0o777)
        except Exception as e: pass
        logging.info(f"✅ Corpus limpio guardado en: {paths['clean_parquet']}")
        
    except Exception as e:
        logging.error(f"Error durante la limpieza de {paths['raw_parquet']}: {e}")
        raise e

def split_corpus(paths, config):
    """Divide el parquet y genera ficheros JSONL."""
    if os.path.exists(paths['jsonl_out_dir']) and os.path.exists(paths['parquet_out_dir']):
        logging.info("Los subdatasets (split) ya existen. Saltando paso.")
        return

    logging.info('-'*30 + ' DIVIDIR PARQUET Y JSONL ' + '-'*30)

    os.makedirs(paths['jsonl_out_dir'], exist_ok=True)
    os.makedirs(paths['parquet_out_dir'], exist_ok=True)
    
    n_partes = config['build']['parts']
    
    # Leemos el dataset limpio
    df = pl.read_parquet(paths['clean_parquet'])
    total_filas = len(df)
    filas_por_parte = total_filas // n_partes

    logging.info(f"Dividiendo {total_filas} filas en {n_partes} partes (~{filas_por_parte} filas/parte).")

    for i in tqdm(range(n_partes), desc="Exportando partes"):
        inicio = i * filas_por_parte
        # Ajuste para que la última parte tome todo el remanente
        fin = (i + 1) * filas_por_parte if i < n_partes - 1 else total_filas
        length = fin - inicio
        
        # Slice es zero-copy en Polars (muy rápido)
        sub_df = df.slice(inicio, length)
        
        part_name = f"archivo_parte_{i + 1}"
        
        # Guardar Parquet
        sub_df.write_parquet(os.path.join(paths['parquet_out_dir'], f"{part_name}.parquet"))
        try: os.chmod(os.path.join(paths['parquet_out_dir'], f"{part_name}.parquet"), 0o777)
        except Exception as e: pass
        
        # Guardar JSONL (NDJSON)
        sub_df.write_ndjson(os.path.join(paths['jsonl_out_dir'], f"{part_name}.jsonl"))
        try: os.chmod(os.path.join(paths['jsonl_out_dir'], f"{part_name}.jsonl"), 0o777)
        except Exception as e: pass

def main():
    # 1. Obtener argumentos
    args = get_args()
    
    # 2. Cargar configuración
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        logging.error("No se encontró config.yaml")
        sys.exit(1)
        
    config = load_config(config_path)

    # 3. Calcular todas las rutas
    paths = get_paths(config, args.name, args.domain, args.version)

    # 4. Ejecutar flujo
    # Paso 1: Generar Raw
    build_raw_corpus(paths, args.name)
    
    # Paso 2: Limpiar
    process_cleaning(paths, config, args.name)
    
    # Paso 3: Dividir y Exportar
    split_corpus(paths, config)
    
    logging.info("\n✅ Proceso completado exitosamente.")

if __name__ == "__main__":
    main()
