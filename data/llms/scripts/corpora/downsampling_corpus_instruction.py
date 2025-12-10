import os, yaml, json, sys, logging, glob
import polars as pl
import re, gc
from pathlib import Path
import time
from polars.datatypes import Int64, String
from typing import List, Optional, Dict

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger: logging.Logger = logging.getLogger(__name__)

# Cargar configuración
config = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "config.yaml"), "r"))

# Params
NAME = config['name']
DOMAIN = config['domain']
SEED = config['seed']
MODE = "instruction"

# Tokenizador
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import TokenManager
TOKENIZER = TokenManager()
logger.info("Initializing TokenManager for token computation...")

# =========================================================================================
# MÉTODOS
# =========================================================================================

def format_instruction_corpus(
    corpus: pl.DataFrame, # polars
    corpus_path: str # ruta absoluta
) -> pl.DataFrame:
    """ Formatea el corpus para tareas de instrucción (prompt + respuesta) """
    
    # 1. Combinar 'prompt', 'question' y 'answer' en una sola columna de texto 'instruction'
    logger.info("Formatting instruction corpus...")
    corpus = corpus.with_columns([
        pl.concat_str([
            pl.col('system_prompt'),
            pl.lit('\n'),
            pl.col('question'),
            pl.lit('\n'),
            pl.col('response')
        ]).alias(config[f'downsampling-{MODE}']['text-column'])
    ])
        
    # 2. Extraer tipos de instrucción del nombre del fichero
    logger.info("Extracting instruction types from filename...")
    # Formato: datos_sinteticos-<dominio>-<tipo:query>-<tipo:context>-<[opcional]tipo:justification>.jsonl
    filename = Path(corpus_path).name
    
    # Patrón regex para extraer los componentes del nombre de archivo
    match = re.search(config[f'downsampling-{MODE}']['pattern'], filename.replace(".jsonl", ""))
    
    if match:
        domain = match.group(1)
        query_type = match.group(2)
        context_type = match.group(3)
        justification_type = match.group(4) if match.group(4) else ""
    else:
        raise ValueError(f"El nombre del archivo no cumple con el formato esperado: {filename}")
    
    # Añadir columnas con los tipos extraídos
    corpus = corpus.with_columns([
        pl.lit(query_type).alias('query_type').cast(pl.Utf8),
        pl.lit(context_type).alias('context_type').cast(pl.Utf8),
        pl.lit(justification_type).alias('justification_type').cast(pl.Utf8)
    ])
    
    # 3. Nueva columna: categoria basada en la combinación de los tipos de instrucción
    logger.info("Creating instruction category column...")
    if justification_type:
        category = f"{query_type}-{context_type}-{justification_type}"
    else:
        category = f"{query_type}-{context_type}"
    corpus = corpus.with_columns([
        pl.lit(category).alias("category")
    ])
    logger.info("\t Category assigned: " + category)
    
    # 4. Nueva columna: número de tokens "tokens" en la instrucción
    logger.info("Computing number of tokens for each instruction...")
    corpus = corpus.with_columns([
        pl.col(
            config[f'downsampling-{MODE}']['text-column']
        ).map_elements(
            lambda text: TOKENIZER.get_tokens(text, disallowed_special=()),
            return_dtype=pl.Int64
        ).alias('tokens')
    ])
    logger.info("\t Token computation completed. Total tokens in corpus: {:,}".format(corpus['tokens'].sum()))
    
    # 5. Forma final del corpus: seleccionar solo las columnas necesarias
    logger.info(f"Selecting final columns for the formatted corpus by context_type '{context_type}'...")
    if context_type == "sin_contexto":
        # Incluir 'source_id' e 'id_chunk' como strings vacios
        corpus = corpus.with_columns([
            pl.lit(f"general_{NAME.replace("-", "_")}").alias("source_id"),
            pl.lit("").alias("id_chunk")
        ])
    corpus = corpus.select([
        'source_id',
        'id_chunk',
        'system_prompt',
        'question',
        'response',
        'category',
        'query_type',
        'context_type',
        'justification_type',
        'tokens'
    ])
    logger.info("\t Formatted instruction corpus shape: {}".format(corpus.shape))
    logger.info("\t -> with columns: {}".format(corpus.columns))
    
    return corpus

def _corpus_statistics(
    corpus: pl.DataFrame, 
    _name: str
) -> pl.DataFrame:
    """ Compute and print basic statistics of the corpus. """
    print(f"Computing statistics for the corpus '{_name}'...")
    with pl.Config(fmt_str_lengths=100, tbl_rows=5, tbl_cols=-1, tbl_width_chars=500):
        print(corpus.sample(5, seed=SEED))
    
    # General: corpus completo
    total_instructions = corpus.shape[0]
    total_tokens = corpus['tokens'].sum()
    avg_tokens = corpus['tokens'].mean()
    print(f"Corpus Statistics:")
    print(f"\t Total instructions: {total_instructions:,}")
    print(f"\t Total tokens: {total_tokens:,}")
    print(f"\t Average tokens per instruction: {avg_tokens:.2f}")
    
    # Initialize list to store all statistics DataFrames
    all_stats = []
    
    # Add overall statistics
    overall_stats = pl.DataFrame({
        'statistic_type': ['Overall'],
        'category': [_name],
        'num_instructions': [total_instructions],
        'total_tokens': [total_tokens],
        'avg_tokens': [avg_tokens]
    })
    all_stats.append(overall_stats)
    
    # !!!
    # General: por tipos (query_type, context_type, justification_type)
    for col in ['query_type', 'context_type', 'justification_type']:
        print(f"Statistics by {col}:")
        stats_by_type = corpus.group_by(col).agg([
            pl.len().alias('num_instructions'),
            pl.sum('tokens').alias('total_tokens'),
            pl.mean('tokens').alias('avg_tokens')
        ]).sort(by='total_tokens', descending=True)
        
        # Add statistic_type column and rename the grouping column to 'category'
        stats_by_type = stats_by_type.with_columns([
            pl.lit(col).alias('statistic_type')
        ]).rename({col: 'category'})
        
        all_stats.append(stats_by_type)
        
        for row in stats_by_type.iter_rows():
            print(f"\t {row[0]}:\t {row[1]:,} instructions\t {row[2]:,} tokens\t {row[3]:.2f} tokens/instruction")
    
    # Específico: estadísticas de cada categoría
    print(f"Statistics by category:")
    stats_by_category = corpus.group_by('category').agg([
        pl.len().alias('num_instructions'),
        pl.sum('tokens').alias('total_tokens'),
        pl.mean('tokens').alias('avg_tokens')
    ]).sort(by='total_tokens', descending=True)
    # !!!
    
    # Add statistic_type column
    stats_by_category = stats_by_category.with_columns([
        pl.lit('category').alias('statistic_type')
    ])
    
    all_stats.append(stats_by_category)
    
    for row in stats_by_category.iter_rows():
        print(f"\t {row[0].replace('-', ' | ')}:\n\t\t {row[1]:,} instructions\n\t\t {row[2]:,} tokens\n\t\t {row[3]:.2f} tokens/instruction")
    
    print()
    print("=" * 50)
    print()
    
    # Cast all DataFrames to consistent types before concatenation
    all_stats_cast = []
    for df in all_stats:
        df_cast = df.with_columns([
            pl.col('num_instructions').cast(pl.Int64),
            pl.col('total_tokens').cast(pl.Int64),
            pl.col('avg_tokens').cast(pl.Float64)
        ])
        all_stats_cast.append(df_cast)
    
    # Concatenate all statistics into a single DataFrame
    stats_df: pl.DataFrame = pl.concat(all_stats_cast, how='diagonal')
    
    # Reorder columns for better readability
    stats_df = stats_df.select(['statistic_type', 'category', 'num_instructions', 'total_tokens', 'avg_tokens'])
    
    return stats_df

def corpus_statistics(
    corpus: pl.DataFrame, 
    _name: str
) -> pl.DataFrame:
    """ Compute and print basic statistics of the corpus. """
    print(f"Computing statistics for the corpus '{_name}'...")
    with pl.Config(fmt_str_lengths=100, tbl_rows=5, tbl_cols=-1, tbl_width_chars=500):
        print(corpus.sample(5, seed=SEED))
    
    # General: corpus completo
    total_instructions = corpus.shape[0]
    total_tokens = corpus['tokens'].sum()
    avg_tokens = corpus['tokens'].mean()
    print(f"Corpus Statistics:")
    print(f"\t Total instructions: {total_instructions:,}")
    print(f"\t Total tokens: {total_tokens:,}")
    print(f"\t Average tokens per instruction: {avg_tokens:.2f}")
    
    # Initialize list to store all statistics DataFrames
    all_stats = []
    
    # Add overall statistics
    overall_stats = pl.DataFrame({
        'statistic_type': ['Overall'],
        'category': [_name],
        'num_instructions': [total_instructions],
        'total_tokens': [total_tokens],
        'avg_tokens': [avg_tokens]
    })
    all_stats.append(overall_stats)
    
    # General: por tipos (query_type, context_type, justification_type)
    for col in ['query_type', 'context_type', 'justification_type']:
        stats_by_type = corpus.group_by(col).agg([
            pl.len().alias('num_instructions'),
            pl.sum('tokens').alias('total_tokens'),
            pl.mean('tokens').alias('avg_tokens')
        ]).sort(by='total_tokens', descending=True)
        
        # Add statistic_type column and rename the grouping column to 'category'
        stats_by_type = stats_by_type.with_columns([
            pl.lit(col).alias('statistic_type')
        ]).rename({col: 'category'})
        
        all_stats.append(stats_by_type)
    
    # Específico: estadísticas de cada categoría
    stats_by_category = corpus.group_by('category').agg([
        pl.len().alias('num_instructions'),
        pl.sum('tokens').alias('total_tokens'),
        pl.mean('tokens').alias('avg_tokens')
    ]).sort(by='total_tokens', descending=True)
    
    # Add statistic_type column
    stats_by_category = stats_by_category.with_columns([
        pl.lit('category').alias('statistic_type')
    ])
    
    all_stats.append(stats_by_category)
    
    print()
    print("=" * 50)
    print()
    
    # Cast all DataFrames to consistent types before concatenation
    all_stats_cast = []
    for df in all_stats:
        df_cast = df.with_columns([
            pl.col('num_instructions').cast(pl.Int64),
            pl.col('total_tokens').cast(pl.Int64),
            pl.col('avg_tokens').cast(pl.Float64)
        ])
        all_stats_cast.append(df_cast)
    
    # Concatenate all statistics into a single DataFrame
    stats_df: pl.DataFrame = pl.concat(all_stats_cast, how='diagonal')
    
    # Reorder columns for better readability
    stats_df = stats_df.select(['statistic_type', 'category', 'num_instructions', 'total_tokens', 'avg_tokens'])
    
    return stats_df

def downsample_corpus_by_tokens(
    corpus: pl.DataFrame = None,
    target_tokens = 0,
) -> pl.DataFrame:
    """
    Downsample corpus to meet a target token budget by randomly selecting rows.
    
    Parameters:
    -----------
    corpus : pl.DataFrame
        DataFrame containing the corpus with a 'tokens' column
    target_tokens : int
        Target number of tokens for the downsampled corpus
        
    Returns:
    --------
    pl.DataFrame
        Downsampled corpus meeting the target token budget
    """
    # Get current total tokens
    try:
        current_tokens = corpus['tokens'].sum()
    except Exception as e:
        logger.error(f"\t Error computing total tokens in corpus: {e}")
        sys.exit(1)
    
    # If already under target, return as is
    if current_tokens <= target_tokens:
        logger.warning(f"Corpus already under target tokens ({current_tokens} <= {target_tokens}). No downsampling needed.")
        return corpus
    
    # Shuffle the corpus with a fixed seed for reproducibility
    shuffled_corpus = corpus.sample(fraction=1.0, shuffle=True, seed=SEED)
    
    # Calculate cumulative sum of tokens
    shuffled_corpus = shuffled_corpus.with_columns(
        pl.col('tokens').cum_sum().alias('cumulative_tokens')
    )
    
    # Filter rows where cumulative sum is less than or equal to target
    downsampled_corpus = shuffled_corpus.filter(
        pl.col('cumulative_tokens') <= target_tokens
    )
    
    # Remove the temporary cumulative_tokens column
    downsampled_corpus = downsampled_corpus.drop('cumulative_tokens')
    
    del shuffled_corpus
    
    return downsampled_corpus

def _finalize_downsampling(
    downsampled_corpus: pl.DataFrame, 
    sampled_parts: List, 
    output_path: str, 
    target_tokens_perc: 50,
    target_tokens: int
):
    
    # Mezclar aleatoriamente el corpus final
    logger.info("Shuffling final corpus for randomization...")
    downsampled_corpus = downsampled_corpus.sample(
        fraction=1.0, 
        shuffle=True, 
        seed=SEED
    )
    
    if sampled_parts:
        # Calcular métricas finales
        total_sampled_tokens = sum([part['tokens'].sum() for part in sampled_parts])
        total_sampled_docs = downsampled_corpus.shape[0]
        
        logger.info("Downsampling completed:")
        logger.info(f"\t Total documents sampled: {total_sampled_docs:,}")
        logger.info(f"\t Total tokens sampled: {total_sampled_tokens:,}")
        logger.info(f"\t Target tokens: {target_tokens:,}")
        
        token_difference = abs(total_sampled_tokens - target_tokens)
        difference_percentage = (token_difference / target_tokens) * 100 if target_tokens > 0 else 0
        logger.info(f"\t Deviation from target: {token_difference:,} tokens ({difference_percentage:.2f}%)")
    
    # Guardar en archivo si está habilitado
    if output_path:        
        logger.info(f"Writing downsampled corpus to disk: {output_path}")
        downsampled_corpus.write_ndjson(output_path)
        logger.info(f"Successfully saved to: {output_path}")
    
    # Mostrar estadísticas
    stats = corpus_statistics(downsampled_corpus, _name=f"Downsampled {MODE} corpus at {target_tokens_perc}%")
    with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=400):
        print(stats)
    stats.write_csv(os.path.join(config[f'downsampling-{MODE}']['path-output-dir'], f"stats_downsample_{target_tokens_perc}_{MODE}_corpus_{NAME}.csv"))

def downsample_corpus_by_proportions(
    proportions: List[int],
    corpus: pl.DataFrame,
    output_dir: Optional[str] = None,
    save_files: bool = True
) -> Dict[int, pl.DataFrame]:
    """
    Realiza downsampling estratificado de un corpus manteniendo las proporciones originales de cada categoría.
    
    Args:
        proportions: Lista de porcentajes objetivo para cada configuración (ej: [0, 30, 50, 70, 100])
        corpus: DataFrame de Polars con columnas mínimas: <category_column>, text_column, 'tokens'
        output_dir: Directorio donde guardar los archivos. Si es None, no se guardan archivos
        save_files: Si True, guarda los corpus en archivos parquet
                
    Raises:
        ValueError: Si el corpus no contiene las columnas requeridas
    """
    
    # Validar columnas requeridas
    required_columns = {config[f'downsampling-{MODE}']['category-column'], 'tokens'}
    if not required_columns.issubset(set(corpus.columns)):
        raise ValueError(f"El corpus debe contener las columnas: {required_columns}. "
                        f"Columnas encontradas: {corpus.columns}")
    
    logger.info("=" * 80)
    logger.info("Initiating stratified downsampling process")
    logger.info("=" * 80)
    
    # Calcular estadísticas por categoría/dataset
    logger.info(f"Calculating token statistics per category (column: '{config[f'downsampling-{MODE}']['category-column']}')...")
    dataset_stats = corpus.group_by(config[f'downsampling-{MODE}']['category-column']).agg([
        pl.col('tokens').sum().alias('total_tokens'),
        pl.len().alias('num_docs')
    ])
    
    logger.info("Dataset statistics computed:")
    with pl.Config(fmt_str_lengths=200, tbl_rows=40):
        print(dataset_stats)
    
    # Calcular proporciones de cada dataset
    dataset_stats = dataset_stats.with_columns([
        (pl.col('total_tokens') / pl.col('total_tokens').sum()).alias('proportion')
    ])
    
    total_tokens = dataset_stats['total_tokens'].sum()
    logger.info(f"Total tokens in corpus: {total_tokens:,}")
    
    # Preparar directorio de salida si es necesario
    if save_files and output_dir:
        import os
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Output directory created/verified: {output_dir}")
        
    # Procesar cada proporción objetivo
    for i, target_tokens_perc in enumerate(proportions, start=1):
        
        output_filename = f"ALIA-{NAME}-{MODE}-{target_tokens_perc}.jsonl"
        output_path = os.path.join(output_dir, output_filename)
        
        if os.path.exists(output_path):
            logger.info(f"Downsampled corpus for target {target_tokens_perc}% already exists at: {output_path}. Skipping...")
            continue
        
        logger.info("=" * 80)
        logger.info(f"Processing Configuration {i}/{len(proportions)}: Target = {target_tokens_perc}%")
        logger.info("=" * 80)
        
        target_tokens = int(total_tokens * (target_tokens_perc / 100))
        
        if target_tokens_perc == 0:
            logger.info("Target tokens set to 0%. Skipping corpus generation for this configuration.")
            continue
        if target_tokens_perc == 100:
            logger.info("Target tokens set to 100%. Saving entire corpus as such.")
            _finalize_downsampling(
                downsampled_corpus=corpus,
                sampled_parts=None,
                output_dir=output_dir if save_files else None,
                target_tokens_perc=target_tokens_perc,
                target_tokens=target_tokens
            )
            continue
        
        logger.info(f"Target tokens for this configuration: {target_tokens:,}")
        
        # Calcular fracción global de muestreo
        current_total = dataset_stats['total_tokens'].sum()
        sampling_fraction = target_tokens / current_total
        
        logger.info(f"Current total tokens available: {current_total:,} -> Target: {target_tokens:,}")
        logger.info(f"Global sampling fraction: {sampling_fraction:.6f}")
        
        if sampling_fraction > 1.0:
            logger.warning(f"Target tokens ({target_tokens:,}) exceeds available tokens ({current_total:,}). "
                          f"Using all available data.")
        
        # Realizar muestreo estratificado por categoría manteniendo proporciones
        logger.info("Initiating stratified sampling across categories...")
        sampled_parts = []
        
        for row in dataset_stats.iter_rows(named=True):
            category = row[config[f'downsampling-{MODE}']['category-column']]
            proportion = row['proportion']
            dataset_tokens = row['total_tokens']
            
            # Calcular cuántos tokens necesitamos de esta categoría
            target_dataset_tokens = int(target_tokens * proportion)
            dataset_sampling_fraction = target_dataset_tokens / dataset_tokens
            
            # Filtrar documentos de esta categoría
            dataset_docs = corpus.filter(pl.col(config[f'downsampling-{MODE}']['category-column']) == category)
            
            # Muestrear documentos de manera aleatoria
            sampled_dataset = dataset_docs.sample(
                fraction=min(dataset_sampling_fraction, 1.0),
                seed=SEED
            )
            
            sampled_parts.append(sampled_dataset)
            
            logger.info(f"\t Category '{category}': sampled {sampled_dataset.shape[0]:,} documents of {dataset_docs.shape[0]:,} in total ({(sampled_dataset.shape[0]/dataset_docs.shape[0])*100}%)")
            logger.info(f"\t -> {sampled_dataset['tokens'].sum():,} tokens ({proportion*100:.2f}% of total)")
        
        # Concatenar todas las partes muestreadas
        logger.info("Concatenating sampled datasets...")
        downsampled_corpus: pl.DataFrame = pl.concat(sampled_parts)
        
        # Finalizar el proceso de downsampling
        _finalize_downsampling(
            downsampled_corpus=downsampled_corpus,
            sampled_parts=sampled_parts,
            output_path=output_path,
            target_tokens_perc=target_tokens_perc,
            target_tokens=target_tokens
        )
    
    logger.info("=" * 80)
    logger.info(f"Stratified downsampling process completed")
    logger.info("=" * 80)
    
    
# =========================================================================================
# MAIN PIPELINE
# =========================================================================================

# =========================================================================================
# 1. Procesar el corpus de instrucciones y guardarlo en formato intermedio

# input -> contiene 'jsonl's
corpus_dir = os.path.join(
    config[f'downsampling-{MODE}']['root'],
    config[f'downsampling-{MODE}']['path-corpus-dir'].format(domain=DOMAIN)
)

# output: interim -> contiene 'jsonl's
corpus_interim_dir = os.path.join(
    config[f'downsampling-{MODE}']['root'],
    config[f'downsampling-{MODE}']['path-corpus-interim-dir'].format(domain=DOMAIN)
)
os.makedirs(corpus_interim_dir, exist_ok=True)

# Comprobar si el corpus ya ha sido procesado I (directorio vacío)
input_len = len(glob.glob(os.path.join(corpus_dir, "*.jsonl")))
output_len = len(glob.glob(os.path.join(corpus_interim_dir, "*.jsonl")))

if not os.listdir(corpus_interim_dir) or output_len < input_len:
    logger.info(f"Processing instruction corpus in directory: {corpus_dir} - [{output_len}<{input_len}]")
    files = sorted(os.listdir(corpus_dir))
    print("Files to process:")
    print("\n\t".join(files))
    print()
    for file in files:
        logger.info(f"Processing file: {file}")
        corpus_path = os.path.join(corpus_dir, file)
        corpus_interim_path = os.path.join(corpus_interim_dir, file)
        if os.path.exists(corpus_interim_path):
            logger.info(f"\t Dataset already in interim: {corpus_interim_path}")
            continue
        try:
            corpus: pl.DataFrame = pl.read_ndjson(corpus_path)
        except Exception as e:
            logger.error(f"Error loading {corpus_path}: {e}")
            continue
        logger.info(f"Loaded dataset from: {corpus_path} with {corpus.shape[0]:,} instructions")
        _start = time.time()
        interim_corpus = format_instruction_corpus(
            corpus=corpus, 
            corpus_path=corpus_path
        )
        logger.info(f"\t Formatting completed in {time.time() - _start:.2f} seconds.")
        del corpus
        # Guardar el corpus de instrucciones procesado
        logger.info(f"Saving interim processed dataset to: {corpus_interim_path}")
        interim_corpus.write_ndjson(corpus_interim_path)
        corpus_statistics(interim_corpus, _name=f"Interim Instruction Corpus from {file}")
        del interim_corpus
        gc.collect()
        logger.info("=" * 50)
else:
    logger.info(f"Instruction corpus already in interim: {corpus_interim_dir}")

# =========================================================================================
# 2. Guardar el corpus completo procesado en formato jsonl

corpus_processed_path = os.path.join(
    config[f'downsampling-{MODE}']['root'],
    config[f'downsampling-{MODE}']['path-corpus-processed-dir'].format(domain=DOMAIN),
    config[f'downsampling-{MODE}']['path-corpus-processed-path'].format(name=NAME)
)

logger.info("=" * 30)
if not os.path.exists(corpus_processed_path):
    logger.info("Combining all processed instruction datasets into a single corpus...")
    interim_files = sorted(glob.glob(os.path.join(corpus_interim_dir, "*.jsonl")))
    # First
    processed_corpus = pl.read_ndjson(interim_files[0])
    # - Get schema
    schema = processed_corpus.schema
    logger.info(f"\t Including interim file: {interim_files[0].split('/')[-1]}.")
    logger.info(f"\t -> Current shape: {processed_corpus.shape}")
    logger.info(f"\t -> Current schema: {processed_corpus.schema}")
    for file in interim_files[1:]:
        _df = pl.read_ndjson(file, schema=schema)
        logger.info(f"\t Including interim file: {file.split('/')[-1]}. Shape: {_df.shape}")
        processed_corpus = processed_corpus.vstack(_df)
        logger.info(f"\t -> Current shape: {processed_corpus.shape}. Total tokens: {processed_corpus['tokens'].sum():,}")
        del _df
    logger.info(f"Saving combined processed instruction corpus to: {corpus_processed_path}")
    _start = time.time()
    processed_corpus.write_ndjson(corpus_processed_path)
    logger.info(f"\t Processed instruction corpus saved with {processed_corpus.shape[0]:,} instructions.")
    logger.info(f"\t -> Save completed in {time.time() - _start:.2f} seconds ({(time.time() - _start)/60:.2f} minutes)")
else:
    if not os.path.exists(
        os.path.join(
            config[f'downsampling-{MODE}']['root'],
            config[f'downsampling-{MODE}']['path-corpus-processed-dir'].format(domain=DOMAIN),
            config[f'downsampling-{MODE}']['path-corpus-downsample-path'].format(name=NAME)
        )
    ):
        logger.info(f"Loading already processed instruction corpus from: {corpus_processed_path}")
        _start = time.time()
        processed_corpus = pl.read_ndjson(corpus_processed_path)
        logger.info(f"\t Processed instruction corpus loaded with {processed_corpus.shape[0]:,} instructions.")
        logger.info(f"\t -> Loading completed in {time.time() - _start:.2f} seconds ({(time.time() - _start)/60:.2f} minutes)")
    else: 
        logger.info(f"Skipping loading processed instruction corpus since downsampled corpus already exists.")
        processed_corpus = None

# Estadísticas
if processed_corpus:
    stats = corpus_statistics(processed_corpus, _name="Processed Instruction Corpus")
    with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=400):
        print(stats)
    stats.write_csv(os.path.join(config[f'downsampling-{MODE}']['path-output-dir'], f"stats_processed_instruction_corpus_{NAME}.csv"))

# =========================================================================================
# 3. Realizar el downsampling de las instrucciones según su tipo

corpus_downsampled_path = os.path.join(
    config[f'downsampling-{MODE}']['root'],
    config[f'downsampling-{MODE}']['path-corpus-processed-dir'].format(domain=DOMAIN),
    config[f'downsampling-{MODE}']['path-corpus-downsample-path'].format(name=NAME)
)

logger.info("=" * 30)
if not os.path.exists(corpus_downsampled_path):

    column_type: str = config[f'downsampling-{MODE}']['category-column']
    column_values: list = config[f'downsampling-{MODE}']['category-values']
    
    # check real column_values
    unique_values = processed_corpus[column_type].unique().to_list()
    logger.info(f"Unique values in column '{column_type}': {unique_values}")
    logger.info(f"Target values: {column_values}")
    # if all items in column_values are in unique_values
    if not all(item in unique_values for item in column_values):
        logger.warning(f"Column values from config do not match unique values in corpus column '{column_type}'. Using unique values {unique_values} from corpus.")
        column_values = unique_values
    
    for i, column_value in enumerate(column_values):
        logger.info(f"Downsampling instruction corpus by category: '{column_value}' into {config[f'downsampling-{MODE}']['downsampling-objectives'][i]:,} tokens")
        # select corpus by category
        corpus_by_type = processed_corpus.filter(
            pl.col(column_type) == column_value
        )
        logger.info(f"\t Corpus for category '{column_value}' has {corpus_by_type.shape[0]:,} instructions and {corpus_by_type['tokens'].sum():,} tokens before downsampling.")
        # downsampling
        target_tokens = config[f'downsampling-{MODE}']['downsampling-objectives'][i]
        downsampled_corpus = downsample_corpus_by_tokens(
            corpus=corpus_by_type,
            target_tokens=target_tokens
        )
        logger.info(f"\t -> After downsampling, category '{column_value}' has {downsampled_corpus.shape[0]:,} instructions and {downsampled_corpus['tokens'].sum():,} tokens.")
        # delete corpus_by_type rows from processed_corpus
        processed_corpus = processed_corpus.filter(
            pl.col(column_type) != column_value
        )
        # concatenate downsampled_corpus to processed_corpus
        processed_corpus = processed_corpus.vstack(downsampled_corpus)

        del corpus_by_type, downsampled_corpus
        gc.collect()

    logger.info(f"Saving downsampled instruction corpus to: {corpus_downsampled_path}")
    _start = time.time()
    processed_corpus.write_ndjson(corpus_downsampled_path)
    logger.info(f"\t Downsampled instruction corpus saved with {processed_corpus.shape[0]:,} instructions.")
    logger.info(f"\t -> Save completed in {time.time() - _start:.2f} seconds ({(time.time() - _start)/60:.2f} minutes)")

else:
    logger.info(f"Loading already downsampled instruction corpus from: {corpus_downsampled_path}")
    _start = time.time()
    processed_corpus = pl.read_ndjson(corpus_downsampled_path)
    logger.info(f"\t Downsampled instruction corpus loaded with {processed_corpus.shape[0]:,} instructions.")
    logger.info(f"\t -> Loading completed in {time.time() - _start:.2f} seconds ({(time.time() - _start)/60:.2f} minutes)")

# Estadísticas
stats = corpus_statistics(processed_corpus, _name="Downsampled Instruction Corpus")
with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=400):
    print(stats)
stats.write_csv(os.path.join(config[f'downsampling-{MODE}']['path-output-dir'], f"stats_downsampled_instruction_corpus_{NAME}.csv"))

# =========================================================================================
# 4. Stratified downsampling by percentage

# Get target proportions for the new downsampled corpora
proportions = config['downsampling-distributions']

# Downsampling 
corpus_processed_dir = os.path.join(
    config[f'downsampling-{MODE}']['root'],
    config[f'downsampling-{MODE}']['path-corpus-processed-dir'].format(domain=DOMAIN)
)

downsample_corpus_by_proportions(
    proportions=proportions,
    corpus=processed_corpus,
    output_dir=corpus_processed_dir
)


