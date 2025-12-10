"""import polars as pl
import os, json, sys, yaml
from tqdm import tqdm
import logging
import gc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_config
from utils.utils_alia import TokenManager

config = load_config(os.path.join(os.path.dirname(__file__), "config.yaml"))

# parámetros generales
DOMAIN = config['domain']
NAME = config['name']
VERSION = config['version']

if VERSION == -1:
    # - directorio del corpus
    corpus_path_dir = os.path.join(
        config['root-corpora'], 
        config['path-corpus-dir'].format( domain=DOMAIN, name=NAME)
    )
    # - info json
    corpus_info_path = os.path.join(
        corpus_path_dir,
        config['path-info'].format(name=NAME)
    )
    # - path del corpus
    corpus_path = os.path.join(
        corpus_path_dir,
        config['path-corpus-parquet'].format(name=NAME)
    )
else:
    # - directorio del corpus
    corpus_path_dir = os.path.join(
        config['root-corpora'], 
        config['path-corpus-dir-version'].format(name=NAME, domain=DOMAIN, version=VERSION)
    )
    # - info json
    corpus_info_path = os.path.join(
        corpus_path_dir,
        config['path-info-version'].format(name=NAME, version=VERSION)
    )
    # - path del corpus
    corpus_path = os.path.join(
        corpus_path_dir,
        config['path-corpus-parquet-version'].format(name=NAME, version=VERSION)
    )    


''' -----------------------------------------------------------------------------------------------
VOLVER A JUNTAR EL CORPUS EN UN PARQUET
'''

logging.info('\n-----------------------------------------------------------------------------------------------')
logging.info("VOLVER A JUNTAR EL CORPUS EN UN PARQUET")
logging.info('-----------------------------------------------------------------------------------------------\n')

import gzip

def read_jsonl_gz_with_polars(folder_path) -> pl.DataFrame:
    dataframes = []
    files = os.listdir(folder_path)
    if len(files) == 0:
        logging.warning(f'No se encontraron archivos en la carpeta: {folder_path}')
        return None
    for filename in os.listdir(folder_path):
        if filename.endswith('.jsonl.gz'):
            full_path = os.path.join(folder_path, filename)
            logging.info(f'Leyendo archivo: {full_path}')
            with gzip.open(full_path, 'rt', encoding='utf-8') as f:
                json_list = [json.loads(line) for line in f]
            df = pl.DataFrame(json_list)
            dataframes.append(df)
    combined_df = pl.concat(dataframes)
    return combined_df

# Ruta de tu carpeta
if not os.path.exists(corpus_path):
    
    folder_path = os.path.join(
        corpus_path_dir,
        config['path-clean-datatrove-dir']
    )
    logging.info(f"Leyendo archivos JSONL comprimidos en: {folder_path}")
    df = read_jsonl_gz_with_polars(folder_path)
    
    if df.is_empty(): 
        logging.error("No se pudo leer ningún archivo. Terminando el proceso.")
        sys.exit(1)

    # Guardar como Parquet
    if not os.path.exists(os.path.dirname(corpus_path)):
        os.mkdir(os.path.dirname(corpus_path))

    df.write_parquet(corpus_path)
    logging.info(f'Archivo Parquet guardado en: {corpus_path}')
else:
    
    if VERSION == -1:
        logging.info(f"El corpus '{NAME}' ya existe en {corpus_path}. No se realiza ninguna acción.")
    else:
        logging.info(f"El corpus final '{NAME}' versión 'v{VERSION}' ya existe en {corpus_path}. No se realiza ninguna acción.")


''' -----------------------------------------------------------------------------------------------
CONTEO DE TOKENS
'''

logging.info('\n-----------------------------------------------------------------------------------------------')
logging.info("CONTEO DE TOKENS")
logging.info('-----------------------------------------------------------------------------------------------\n')

def _token_extract(output_path, count_path, _write: bool = True):
    df = pl.read_parquet(output_path)

    tm = TokenManager()

    # Añadir tokens usando la versión optimizada con apply vectorizado
    df = tm.add_tokens_column_to_dataset(
        dataset=df,
        text_column="text"
    )

    # Extraer source_id
    df = df.with_columns([
        pl.col("metadata").struct.field("source_id").alias("source_id")
    ])
    
    print(df.head())

    # Convertir a LazyFrame para procesamiento diferido
    ldf = df.lazy()

    # Agrupar y agregar (suma tokens y cuenta)
    conteo_completo_lazy = ldf.group_by("source_id").agg([
        pl.sum("tokens").alias("total_tokens"),
        pl.len().alias("count")
    ]).sort("total_tokens", descending=True)

    conteo_completo = conteo_completo_lazy.collect()
    
    print(conteo_completo.head())

    # Calcular totales generales
    total_tokens_sum = conteo_completo['total_tokens'].sum()
    total_count_sum = conteo_completo['count'].sum()

    # Crear DataFrame con la fila total
    total_df = pl.DataFrame({
        "source_id": ["total"],
        "total_tokens": [total_tokens_sum],
        "count": [total_count_sum]
    })

    types_dict = conteo_completo.schema
    total_df = total_df.with_columns([
        pl.col("total_tokens").cast(types_dict["total_tokens"]),
        pl.col("count").cast(types_dict["count"])
    ])
    
    with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=500):
        print(total_df)

    # Concatenar el total al DataFrame original
    conteo_completo_final = pl.concat([conteo_completo, total_df])

    if _write: conteo_completo_final.write_csv(count_path)

    logging.info(f"Suma total de tokens: {total_tokens_sum}")
    logging.info(f"Guardado conteo completo con fila total (suma tokens y cantidad de filas) por source_id en '{count_path}'.")

def token_extract(output_path, count_path, _write: bool = True):
    df = pl.read_parquet(output_path)

    tm = TokenManager()

    # Añadir tokens usando la versión optimizada con apply vectorizado
    df = tm.add_tokens_column_to_dataset(
        dataset=df,
        text_column="text"
    )

    # Extraer source_id
    df = df.with_columns([
        pl.col("metadata").struct.field("source_id").alias("source_id")
    ])
    
    print(df.head())
    
    # Agrupar y agregar sin LazyFrame
    conteo_completo = df.group_by("source_id").agg([
        pl.sum("tokens").alias("total_tokens"),
        pl.len().alias("count")
    ]).sort("total_tokens", descending=True)
    
    del df
    gc.collect()
    
    print(conteo_completo.head())

    # Calcular totales generales
    total_tokens_sum = conteo_completo['total_tokens'].sum()
    total_count_sum = conteo_completo['count'].sum()

    # Crear DataFrame con la fila total
    total_df = pl.DataFrame({
        "source_id": ["total"],
        "total_tokens": [total_tokens_sum],
        "count": [total_count_sum]
    })

    types_dict = conteo_completo.schema
    total_df = total_df.with_columns([
        pl.col("total_tokens").cast(types_dict["total_tokens"]),
        pl.col("count").cast(types_dict["count"])
    ])
    
    with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=500):
        print(total_df)

    # Concatenar el total al DataFrame original
    conteo_completo_final = pl.concat([conteo_completo, total_df])
    
    del conteo_completo, total_df
    gc.collect()

    if _write:
        conteo_completo_final.write_csv(count_path)

    logging.info(f"Suma total de tokens: {total_tokens_sum}")
    logging.info(f"Guardado conteo completo con fila total (suma tokens y cantidad de filas) por source_id en '{count_path}'.")


if VERSION == -1:
    count_path = os.path.join(
        corpus_path_dir,
        config['path-count'].format(name=NAME)
    )
else:
    count_path = os.path.join(
        corpus_path_dir,
        config['path-count-version'].format(name=NAME, version=VERSION)
    )
if not os.path.exists(count_path):
    token_extract(
        output_path = corpus_path,
        count_path = count_path
    )
else:
    logging.info(f"El conteo de tokens ya existe en '{count_path}'. No se realiza ninguna acción.")

''' -----------------------------------------------------------------------------------------------
SACAR INFORMACIÓN DE TOKENS
'''

logging.info('\n-----------------------------------------------------------------------------------------------')
logging.info("SACAR INFORMACIÓN DE TOKENS")
logging.info('-----------------------------------------------------------------------------------------------\n')

conteo = pl.read_csv(count_path)
conteo.sort("source_id")

with open(corpus_info_path, "r") as f: info = json.load(f)

if 'info' not in info.keys():

    datasets = []
    corpus_info = {}
    total = 0
    instances = 0
    for row in conteo.iter_rows(named=True):
        if not (row['source_id'] == "total"):
            datasets.append(row['source_id'])
            corpus_info[row['source_id']] = {
                'tokens': row['total_tokens'],
                'instances': row['count']
            }
            total += row['total_tokens']
            instances += row['count']

    info['datasets'] = sorted(datasets)
    info['info'] = corpus_info
    info['total-tokens'] = total
    info['total-tokens-mill'] = total/1_000_000
    info['total-tokens-bill'] = total/1_000_000_000
    info['total-instances'] = instances

    for row in conteo.iter_rows(named=True):
        if not (row['source_id'] == "total"):
            _instances = row['count']
            _tokens = row['total_tokens']
            info['info'][row['source_id']]["tokens%"] = (_tokens / total).__round__(4)
            info['info'][row['source_id']]["instances%"] = (_instances / instances).__round__(4)
            
    info['info'] = dict(sorted(info['info'].items(), key=lambda item: item[1]['tokens%'], reverse=True))

    json.dump(info, open(corpus_info_path, "w"), indent=4)

else:
    if VERSION == -1:
        logging.info(f"El corpus '{NAME}' ya tiene información de tokens en '{corpus_info_path.split('/')[-1]}'. No se realiza ninguna acción.")
    else:
        logging.info(f"El corpus '{NAME}' versión 'v{VERSION}' ya tiene información de tokens en '{corpus_info_path.split('/')[-1]}'. No se realiza ninguna acción.")
"""

import polars as pl
import os
import json
import sys
import argparse
import gzip
import logging
import gc
from tqdm import tqdm

# Configuración de logging
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

sys.path.append(os.path.realpath("./"))
try:
    from utils.utils_alia import load_config, TokenManager
except ImportError:
    # Fallback para pruebas si no existe la estructura de directorios
    import yaml
    class TokenManager: # Dummy class
        def add_tokens_column_to_dataset(self, dataset, text_column): return dataset.with_columns(pl.lit(100).alias("tokens"))
    def load_config(path):
        with open(path, 'r') as f: return yaml.safe_load(f)

def get_args():
    """Captura los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Script de finalización de Corpus")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    return parser.parse_args()

def get_paths(config, name, domain, version):
    """Centraliza la lógica de generación de rutas."""
    
    if version == -1:
        base_dir = os.path.join(
            config['root-corpora'], 
            config['path-corpus-dir'].format(domain=domain, name=name)
        )
        info_filename = config['path-info'].format(name=name)
        corpus_parquet = config['path-corpus-parquet'].format(name=name)
        count_filename = config['path-count'].format(name=name)
    else:
        base_dir = os.path.join(
            config['root-corpora'], 
            config['path-corpus-dir-version'].format(name=name, domain=domain, version=version)
        )
        info_filename = config['path-info-version'].format(name=name, version=version)
        corpus_parquet = config['path-corpus-parquet-version'].format(name=name, version=version)
        count_filename = config['path-count-version'].format(name=name, version=version)

    return {
        "base_dir": base_dir,
        "info_json": os.path.join(base_dir, info_filename),
        "corpus_parquet": os.path.join(base_dir, corpus_parquet),
        "datatrove_clean_dir": os.path.join(base_dir, config['path-clean-datatrove-dir']),
        "token_count_csv": os.path.join(base_dir, count_filename)
    }

def read_jsonl_gz_folder(folder_path) -> pl.DataFrame:
    """Lee todos los archivos .jsonl.gz de una carpeta y devuelve un DataFrame unificado."""
    if not os.path.exists(folder_path):
        logging.error(f"La carpeta no existe: {folder_path}")
        return None

    files = [f for f in os.listdir(folder_path) if f.endswith('.jsonl.gz')]
    
    if not files:
        logging.warning(f'No se encontraron archivos .jsonl.gz en: {folder_path}')
        return None

    dataframes = []
    # Usamos tqdm para barra de progreso
    for filename in tqdm(files, desc="Leyendo JSONL GZ"):
        full_path = os.path.join(folder_path, filename)
        try:
            with gzip.open(full_path, 'rt', encoding='utf-8') as f:
                # Leemos línea a línea para evitar errores de memoria masivos si el jsonl es gigante
                # Aunque para máxima velocidad, read_ndjson de polars es mejor si el fichero está descomprimido
                json_list = [json.loads(line) for line in f]
            
            if json_list:
                df = pl.DataFrame(json_list)
                dataframes.append(df)
        except Exception as e:
            logging.error(f"Error leyendo {filename}: {e}")

    if not dataframes:
        return None
        
    return pl.concat(dataframes)

def merge_jsonl_to_parquet(paths, name, version):
    """Paso 1: Une los JSONL (salida de DataTrove) en un único Parquet."""
    if os.path.exists(paths['corpus_parquet']):
        v_str = f"v{version}" if version != -1 else "base"
        logging.info(f"El corpus final '{name}' ({v_str}) ya existe. Saltando paso.")
        return

    logging.info('\n' + '-'*30 + ' UNIFICAR CORPUS A PARQUET ' + '-'*30)
    
    logging.info(f"Leyendo archivos de: {paths['datatrove_clean_dir']}")
    df = read_jsonl_gz_folder(paths['datatrove_clean_dir'])
    
    if df is None or df.is_empty():
        logging.error("No se pudo leer ningún archivo o la carpeta está vacía.")
        sys.exit(1)

    os.makedirs(os.path.dirname(paths['corpus_parquet']), exist_ok=True)
    
    df.write_parquet(paths['corpus_parquet'])
    logging.info(f"✅ Archivo Parquet guardado en: {paths['corpus_parquet']}")
    
    # Limpieza explícita
    del df
    gc.collect()

def count_tokens(paths):
    """Paso 2: Calcula tokens por source_id y total."""
    if os.path.exists(paths['token_count_csv']):
        logging.info("El conteo de tokens ya existe. Saltando paso.")
        return

    logging.info('\n' + '-'*30 + ' CONTEO DE TOKENS ' + '-'*30)
    
    # Cargar dataset
    df = pl.read_parquet(paths['corpus_parquet'])
    
    # Instanciar TokenManager
    tm = TokenManager()
    
    logging.info("Calculando tokens (esto puede tardar)...")
    # Añadir columna tokens
    df = tm.add_tokens_column_to_dataset(dataset=df, text_column="text")

    # Extraer source_id de la struct metadata
    # Asumimos que metadata existe y tiene source_id
    if "metadata" in df.columns:
        df = df.with_columns(
            pl.col("metadata").struct.field("source_id").alias("source_id")
        )
    else:
        logging.warning("No se encontró columna 'metadata'. Usando 'unknown' como source_id.")
        df = df.with_columns(pl.lit("unknown").alias("source_id"))

    # Agregación
    conteo = df.group_by("source_id").agg([
        pl.sum("tokens").alias("total_tokens"),
        pl.len().alias("count")
    ]).sort("total_tokens", descending=True)
    
    # Liberar memoria del df grande
    del df
    gc.collect()

    # Calcular totales
    total_tokens = conteo['total_tokens'].sum()
    total_count = conteo['count'].sum()
    
    logging.info(f"Total Tokens: {total_tokens} | Total Instances: {total_count}")

    # Crear fila de totales manteniendo tipos
    schema = conteo.schema
    total_row = pl.DataFrame({
        "source_id": ["total"],
        "total_tokens": [total_tokens],
        "count": [total_count]
    }).with_columns([
        pl.col("total_tokens").cast(schema["total_tokens"]),
        pl.col("count").cast(schema["count"])
    ])

    conteo_final = pl.concat([conteo, total_row])
    
    # Guardar
    conteo_final.write_csv(paths['token_count_csv'])
    logging.info(f"✅ Conteo guardado en: {paths['token_count_csv']}")

def update_corpus_info(paths):
    """Paso 3: Actualiza el JSON de información del corpus con estadísticas."""
    logging.info('\n' + '-'*30 + ' ACTUALIZAR INFO JSON ' + '-'*30)
    
    if not os.path.exists(paths['info_json']):
        logging.error(f"No existe el archivo de info: {paths['info_json']}")
        return

    with open(paths['info_json'], "r") as f:
        info = json.load(f)

    # Si ya tiene info, saltamos (para evitar sobrescribir si se corre varias veces)
    if 'total-tokens' in info:
         logging.info("El JSON ya contiene información de tokens. Saltando actualización.")
         return

    # Leer el CSV generado en el paso anterior
    if not os.path.exists(paths['token_count_csv']):
        logging.error("No se encuentra el CSV de conteo de tokens.")
        return

    conteo_df = pl.read_csv(paths['token_count_csv'])
    
    # Procesar datos
    datasets_list = []
    corpus_stats = {}
    
    # Filtrar la fila total para cálculos
    rows = conteo_df.filter(pl.col("source_id") != "total")
    total_tokens = rows["total_tokens"].sum()
    total_instances = rows["count"].sum()

    for row in rows.iter_rows(named=True):
        sid = row['source_id']
        datasets_list.append(sid)
        corpus_stats[sid] = {
            'tokens': row['total_tokens'],
            'instances': row['count'],
            'tokens%': round(row['total_tokens'] / total_tokens, 4) if total_tokens > 0 else 0,
            'instances%': round(row['count'] / total_instances, 4) if total_instances > 0 else 0
        }

    # Ordenar por porcentaje de tokens
    corpus_stats = dict(sorted(corpus_stats.items(), key=lambda x: x[1]['tokens%'], reverse=True))

    # Actualizar diccionario
    info['datasets'] = sorted(datasets_list)
    info['info'] = corpus_stats
    info['total-tokens'] = total_tokens
    info['total-tokens-mill'] = total_tokens / 1_000_000
    info['total-tokens-bill'] = total_tokens / 1_000_000_000
    info['total-instances'] = total_instances

    with open(paths['info_json'], "w") as f:
        json.dump(info, f, indent=4)
        
    logging.info(f"✅ Información actualizada en: {paths['info_json']}")

def main():
    # 1. Argumentos
    args = get_args()
    
    # 2. Configuración
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        logging.error("No se encontró config.yaml")
        sys.exit(1)
    config = load_config(config_path)

    # 3. Rutas
    paths = get_paths(config, args.name, args.domain, args.version)
    
    # 4. Flujo de ejecución
    merge_jsonl_to_parquet(paths, args.name, args.version)
    count_tokens(paths)
    update_corpus_info(paths)
    
    logging.info("\n✅ Proceso completado exitosamente.")

if __name__ == "__main__":
    main()

