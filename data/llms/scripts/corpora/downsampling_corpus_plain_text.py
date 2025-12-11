import os, yaml, json, sys, logging
import polars as pl

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
MODE = "raw"

corpus_path = os.path.join(
    config['root-corpora'],
    config['path-corpus-dir'].format(name=NAME, domain=DOMAIN),
    config['path-corpus-parquet'].format(name=NAME)
)

corpus_info_path = os.path.join(
    config['root-corpora'],
    config['path-corpus-dir'].format(name=NAME, domain=DOMAIN),
    config['path-info'].format(name=NAME)
)
corpus_info = json.load(open(corpus_info_path, "r"))

logger.info(f"Corpus information path: {corpus_info_path}")
logger.info(f"Total datasets in corpus: {len(corpus_info['datasets'])}")

""" ---------------------------------------------------------------------------------------------------
1. Comprobar si existe el corpus con los tokens
"""
corpus_path_tokens = os.path.join(
    config['root-corpora'],
    config['path-corpus-dir'].format(name=NAME, domain=DOMAIN),
    config['downsampling-raw']['path-corpus-tokens-parquet'].format(name=NAME)
)

if not os.path.exists(corpus_path_tokens):
    
    logger.info(f"Loading corpus from: {corpus_path}")
    corpus = pl.read_parquet(corpus_path) 

    sys.path.append(os.path.realpath("./"))
    from utils.utils_alia import TokenManager

    tokenizer = TokenManager()
    logger.info("Initializing TokenManager for token computation...")
    logger.info("Computing tokens for all documents in corpus (this may take several minutes)...")

    corpus = corpus.with_columns([
        pl.col(config['downsampling-raw']['text-column']).map_elements(
            lambda text: tokenizer.get_tokens(text),
            return_dtype=pl.Int64
        ).alias('tokens')
    ])

    logger.info(f"Token computation completed: {corpus.shape[0]:,} documents processed")
    logger.debug(f"Corpus schema: {corpus.columns}")
    corpus.write_parquet(corpus_path_tokens)

else:
    
    logger.info(f"Loading corpus with tokens from: {corpus_path_tokens}")
    corpus = pl.read_parquet(corpus_path_tokens)

""" ---------------------------------------------------------------------------------------------------
2. Mostrar proporciones ORIGINALES de cada dataset
"""

logger.info("Loading original dataset proportions...")
proportions = corpus_info['info']
datasets, tokens, percentages = [], [], []
for dataset, entry in proportions.items():
    datasets.append(dataset)
    tokens.append(entry['tokens'])
    percentages.append(entry['tokens%']*100)

df = pl.DataFrame({
    "dataset": datasets,
    "tokens": tokens,
    "percentage": percentages
})

df = df.sort("tokens", descending=True)

logger.info("Original dataset distribution:")
with pl.Config(fmt_str_lengths=200, tbl_rows=40):
    print(df)

total_tokens = df['tokens'].sum()
logger.info(f"Total tokens in corpus: {total_tokens:,}")

# Definir los objetivos de tokens para cada entrenamiento
training_objectives_raw = config['downsampling-distributions']

""" ---------------------------------------------------------------------------------------------------
3. Realizar downsampling estratificado del corpus
"""

# Obtener el total de tokens por dataset en el corpus actual
logger.info("Calculating token statistics per dataset...")
dataset_stats = corpus.group_by(config['downsampling-raw']['category-column']).agg([
    pl.col('tokens').sum().alias('total_tokens'),
    pl.len().alias('num_docs')
])

logger.info("Dataset statistics computed:")
with pl.Config(fmt_str_lengths=200, tbl_rows=40):
    print(dataset_stats)

# Calcular las proporciones de cada dataset
dataset_stats = dataset_stats.with_columns([
    (pl.col('total_tokens') / pl.col('total_tokens').sum()).alias('proportion')
])

# Crear múltiples versiones del corpus con diferentes objetivos de downsampling
output_dir = os.path.join(
    config['root-corpora'],
    config['path-corpus-dir'].format(name=NAME, domain=DOMAIN),
    'downsampled'
)
os.makedirs(output_dir, exist_ok=True)
logger.info(f"Output directory created/verified: {output_dir}")

for i, target_tokens_perc in enumerate(training_objectives_raw, start=1):
    logger.info("=" * 80)
    logger.info(f"Processing Training Configuration {i}: Target RAW tokens = {target_tokens_perc}%")
    logger.info("=" * 80)
    
    target_tokens = int(total_tokens * (target_tokens_perc/100))
    
    if target_tokens == 0:
        logger.info("Target tokens set to 0%. Skipping RAW corpus generation for this configuration.")
        continue
    
    logger.info(f"Target tokens for this configuration: {target_tokens:,}")
    # Calcular la fracción global de muestreo
    current_total = dataset_stats['total_tokens'].sum()
    sampling_fraction = target_tokens / current_total
    
    logger.info(f"Current total tokens available: {current_total:,}")
    logger.info(f"Global sampling fraction: {sampling_fraction:.6f}")
    
    if sampling_fraction > 1.0:
        logger.warning(f"Target tokens ({target_tokens:,}) exceeds available tokens ({current_total:,}). "
                      f"Using all available data.")
    
    # Realizar muestreo estratificado por dataset manteniendo proporciones
    logger.info("Initiating stratified sampling across datasets...")
    sampled_parts = []
    
    for row in dataset_stats.iter_rows(named=True):
        category = row[config['downsampling-raw']['category-column']]
        proportion = row['proportion']
        dataset_tokens = row['total_tokens']
        
        # Calcular cuántos tokens necesitamos de este dataset
        target_dataset_tokens = int(target_tokens * proportion)
        dataset_sampling_fraction = target_dataset_tokens / dataset_tokens
        
        # Filtrar documentos de este dataset
        dataset_docs = corpus.filter(pl.col(config['downsampling-raw']['category-column']) == category)
        
        # Muestrear documentos de manera aleatoria
        sampled_dataset = dataset_docs.sample(
            fraction=min(dataset_sampling_fraction, 1.0),
            seed=42 + i
        )
        
        sampled_parts.append(sampled_dataset)
        
        logger.info(f"  Dataset '{category}': sampled {sampled_dataset.shape[0]:,} documents "
                   f"({sampled_dataset['tokens'].sum():,} tokens, {proportion*100:.2f}% of total)")
    
    # Concatenar todas las partes muestreadas
    logger.info("Concatenating sampled datasets...")
    downsampled_corpus = pl.concat(sampled_parts)
    
    # Mezclar aleatoriamente el corpus final
    logger.info("Shuffling final corpus for randomization...")
    downsampled_corpus = downsampled_corpus.sample(
        fraction=1.0, 
        shuffle=True, 
        seed=42 + i
    )
    
    # Eliminar columnas auxiliares antes de guardar
    downsampled_corpus = downsampled_corpus.select(['source_id', 'id', 'text', 'tokens'])
    
    total_sampled_tokens = sum([part['tokens'].sum() for part in sampled_parts])
    total_sampled_docs = downsampled_corpus.shape[0]
    
    logger.info("Downsampling completed:")
    logger.info(f"  Total documents sampled: {total_sampled_docs:,}")
    logger.info(f"  Total tokens sampled: {total_sampled_tokens:,}")
    logger.info(f"  Target tokens: {target_tokens:,}")
    
    token_difference = abs(total_sampled_tokens - target_tokens)
    difference_percentage = (token_difference / target_tokens) * 100
    logger.info(f"  Deviation from target: {token_difference:,} tokens ({difference_percentage:.2f}%)")
    
    # Guardar el corpus downsampled
    output_filename = f"ALIA-{NAME}-{target_tokens_perc}.parquet"
    output_path = os.path.join(output_dir, output_filename)
    
    logger.info(f"Writing downsampled corpus to disk: {output_filename}")
    downsampled_corpus.write_parquet(output_path)
    logger.info(f"Successfully saved to: {output_path}")

logger.info("=" * 80)
logger.info("Downsampling process completed successfully for all training configurations")
logger.info("=" * 80)
