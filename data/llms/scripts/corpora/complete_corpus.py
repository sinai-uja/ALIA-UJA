import polars as pl
import os, sys, glob
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
import json
import logging, argparse
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_config, load_csv, load_parquet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def aggregate_corpus(dir_path: str, output_path: str):
    """
    Agrega todos los archivos parquet en un directorio en un único DataFrame y lo guarda.

    Args:
        dir_path (str): Directorio donde buscar archivos .parquet.
        output_path (str): Ruta donde guardar el parquet agregado.

    Returns:
        pl.DataFrame or None: DataFrame agregado o None en caso de error.
    """
    try:
        list_parquet = glob.glob(f"{dir_path}/*.parquet")
        if not list_parquet:
            raise FileNotFoundError(f"No se encontraron ficheros parquet en {dir_path}")
        df = (
            pl.scan_parquet(
                list_parquet,
                cast_options=pl.ScanCastOptions(extra_struct_fields="ignore")
            )
            .collect(engine="auto")
        )
        df.write_parquet(output_path)
        return df
    except Exception as e:
        logging.exception(f"Error al agregar los ficheros del corpus en {output_path}: {e}")
        return None

def map_corpus_source_id(corpus: pl.DataFrame, mapping: pl.DataFrame):
    """
    Aplica el mapping al campo source_id del corpus para unificar datasets.

    Args:
        corpus (pl.DataFrame): DataFrame del corpus original.
        mapping (pl.DataFrame): DataFrame del mapping entre datasets.

    Returns:
        pl.DataFrame: Corpus con source_id mapeado.
    """
    return (
        corpus
        .join(mapping, left_on="source_id", right_on="original_dataset", how="left")
        .with_columns(
            pl.when(pl.col("mapped_dataset").is_not_null())
            .then(pl.col("mapped_dataset"))
            .otherwise(pl.col("source_id"))
            .alias("source_id")
        )
        .select(["source_id", "id", "text"])
        .sort("source_id")
    )

def get_unique_datasets(corpus: pl.DataFrame):
    """
    Obtiene la lista ordenada de datasets únicos en el corpus.

    Args:
        corpus (pl.DataFrame): Corpus con columna source_id.

    Returns:
        list: Lista ordenada de datasets únicos.
    """
    return sorted(corpus["source_id"].unique().to_list())

def find_parquet_files(dataset_path_dir: str, domain: str):
    """
    Busca recursivamente todos los archivos parquet en el directorio especificado para un dominio.

    Args:
        dataset_path_dir (str): Directorio base con formato para dominio.
        domain (str): Nombre del dominio para formatear ruta.

    Returns:
        list: Lista de rutas absolutas a archivos parquet encontrados.
    """
    return [
        os.path.join(root, file)
        for root, _, files in os.walk(dataset_path_dir.format(domain=domain))
        for file in files if file.endswith(".parquet")
    ]

def process_dataset(ds: str, datasets_metadata_cols: list, corpus: pl.DataFrame, parquet_files: list, output_dir: str, force: bool):
    """
    Procesa un dataset específico: carga, enriquece con metadatos y guarda si no existe o si force=True.

    Args:
        ds (str): Nombre del dataset a procesar.
        datasets_metadata_cols (list): Lista de columnas metadata a incluir.
        corpus (pl.DataFrame): Corpus filtrado para hacer join.
        parquet_files (list): Lista de archivos parquet disponibles.
        output_dir (str): Directorio para guardar datasets enriquecidos.
        force (bool): Indica si sobreescribir datasets existentes.
    """
    try:
        dataset_path = next((p for p in parquet_files if os.path.basename(os.path.dirname(p)) == ds), None)
        if not dataset_path:
            logging.error(f"\t⚠️ Dataset '{ds}' not found in processed datasets.")
            return

        output_path = os.path.join(output_dir, f"{ds}.parquet")
        # Si el dataset ya existe y no se fuerza, se salta
        if os.path.exists(output_path) and not force:
            logging.info(f"\t✅ Enriched dataset '{ds}' already exists. Skipping...")
            return

        logging.info(f"Processing dataset: {ds}")

        try:
            dataset = load_parquet(dataset_path)
            # Forzar columnas a texto (Utf8) para evitar problemas
            dataset = dataset.with_columns([pl.col(c).cast(pl.Utf8) for c in dataset.columns])
        except Exception as e:
            logging.exception(f"Error al leer el dataset {dataset_path}: {e}")
            return

        # Filtrar corpus por source_id actual para el join
        subset = corpus.filter(pl.col("source_id") == ds)

        # Seleccionar columnas de metadata que existan en el dataset
        metadata_cols = [c for c in datasets_metadata_cols if c in dataset.columns]
        
        if metadata_cols:
            # Enriquecer con las columnas metadata en JSON
            joined = subset.join(dataset.select(["id"] + metadata_cols), on="id", how="left")
            enriched = joined.with_columns(
                pl.struct([pl.col(c) for c in metadata_cols])
                .map_elements(lambda x: json.dumps(x, ensure_ascii=False), return_dtype=pl.Utf8)
                .alias("metadata")
            ).select(["source_id", "id", "text", "metadata"])
        else:
            # Si no hay metadata, añadir columna vacía '{}'
            enriched = subset.with_columns(pl.lit("{}").alias("metadata")).select(["source_id", "id", "text", "metadata"])

        # Mostrar ejemplo con todas columnas excepto 'text' (para visualización rápida)
        example = enriched.head(1).select(pl.exclude("text"))
        with pl.Config(fmt_str_lengths=200, tbl_rows=1):
            print(f"Example\n{example}")

        # Guardar dataset enriquecido
        enriched.write_parquet(output_path, use_pyarrow=True)
        logging.info(f"✅ Saved enriched dataset: {output_path}")

    except Exception as e:
        logging.exception(f"❌ [FATAL] Error processing dataset '{ds}': {e}")

def main(force: bool = False):
    # Cargar configuración desde archivo YAML
    config = load_config(os.path.join(os.path.realpath(__file__), "config.yaml"))

    # Crear directorio de salida para corpus enriquecido
    output_dir = os.path.join(
        config['root-corpora'], 
        config['path-corpus-enriched-dir'].format(
            domain=config['domain'],
            name=config['name']
        )    
    )
    os.makedirs(output_dir, exist_ok=True)

    corpus_output_path = os.path.join(
        output_dir, 
        config['completion']['path-corpus-enriched-parquet']
    )
    # Solo procesar si el corpus enriquecido no existe aun
    if not os.path.exists(corpus_output_path):
        logging.info("Loading corpus...")
        corpus_dir = os.path.join(
            config['root-corpora'],
            config['path-corpus-dir'].format(
                domain=config['domain'], 
                name=config['name']
            )
        )
        corpus_path = os.path.join(
            corpus_dir,
            config['path-corpus-parquet'].format(
                name=config['name']
            )
        )
        corpus = load_parquet(corpus_path)
        logging.info("Corpus loaded")
        print(corpus.head(5))
        if "source_id" not in corpus.columns:
            logging.error("El corpus no contiene la columna 'source_id'. Creando...")
            # Extraer source_id
            corpus = corpus.with_columns([
                pl.col("metadata").struct.field("source_id").alias("source_id")
            ])
            corpus = corpus.drop("metadata")
            logging.info("Columna 'source_id' creada.")

        logging.info("Loading mapping...")
        mapping_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), 
            config['completion']['dataset-mapping']
        )
        mapping = load_csv(mapping_path)

        logging.info("Mapping corpus source_id...")
        corpus = map_corpus_source_id(corpus, mapping)

        datasets = get_unique_datasets(corpus)
        logging.info(f"- Found {len(datasets)} datasets.")

        # Columnas de metadata a extraer para cada dominio
        columns_metadata = config['completion']['features'][config['domain']]

        parquet_files = find_parquet_files(config["dataset_path_dir"].format(domain=config['domain']), config['domain'])
        logging.info(f"- Found {len(parquet_files)} parquet files.")

        # Procesar cada dataset individualmente para enriquecerlo
        for ds in datasets:
            process_dataset(ds, columns_metadata, corpus, parquet_files, output_dir, force)

        logging.info("Corpus enriquecido guardado correctamente.")
        print("Corpus enriquecido guardado correctamente.")

        # Agregar todos los datasets enriquecidos en un único archivo parquet
        df = aggregate_corpus(output_dir, corpus_output_path)
        with pl.Config(fmt_str_lengths=250, tbl_rows=10):
            print(df)

# MAIN
if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="Procesar corpus y datasets enriquecidos")
    parser.add_argument(
        '--force',
        action='store_true',
        help='Forzar procesamiento incluso si los datasets enriquecidos ya existen'
    )
    args = parser.parse_args()

    force = args.force  # True si se usa --force, False si no se especifica

    main(force=force)


