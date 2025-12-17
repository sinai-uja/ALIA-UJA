import polars as pl
import json
from tqdm import tqdm
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import os
import pickle
import yaml
from vllm import LLM
import gc
import logging
from datetime import datetime
import sys
import shutil
import glob
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager

# Configurar logging
log_dir = Path('./logs')
log_dir.mkdir(exist_ok=True)
log_filename = log_dir / f'persona_processing_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@contextmanager
def log_time(operation: str):
    """Context manager para logging de tiempo"""
    start = datetime.now()
    logger.info(f'⏱️  Iniciando: {operation}')
    try:
        yield
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f'✅ Completado: {operation} ({elapsed:.2f}s)')

def load_config(config_path: str = 'config_persona.yaml') -> dict:
    """Cargar configuración desde YAML"""
    logger.info(f'Cargando configuración desde: {config_path}')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def setup_environment(config: dict):
    """Configurar variables de entorno"""
    num_threads = str(config.get('cpus_per_task', '8'))
    os.environ.update({
        'OMP_NUM_THREADS': num_threads,
        'MKL_NUM_THREADS': num_threads,
        'OPENBLAS_NUM_THREADS': num_threads
    })
    logger.info(f'Threads configurados: {num_threads}')

def initialize_llm(config: dict) -> LLM:
    """Inicializar modelo vLLM con configuración optimizada"""
    with log_time('Inicialización modelo vLLM'):
        max_batched = max(config['max_model_len'], 32768)

        llm = LLM(
            model=config['model_path'],
            task="embed",
            tensor_parallel_size=config['tensor_parallel_size'],
            max_model_len=config['max_model_len'],
            gpu_memory_utilization=config['gpu_utilization'],
            seed=config['seed'],
            max_num_batched_tokens=max_batched,
            max_num_seqs=config['batch_size'] * 4,
            disable_custom_all_reduce=True,
            disable_log_stats=True,
            enable_chunked_prefill=True,
        )
    return llm

def get_embeddings_batch(llm: LLM, texts: List[str], tokenizer, max_len: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Obtener embeddings en batch.
    Retorna: (embeddings_array, valid_indices_mask)
    """
    if not texts:
        return np.array([]), np.array([])

    valid_mask = []
    processed_texts = []

    for i, text in enumerate(texts):
        if not text or not text.strip():
            valid_mask.append(False)
            continue

        num_tokens = len(tokenizer.encode(text))
        if num_tokens > max_len:
            valid_mask.append(False)
        else:
            valid_mask.append(True)
            processed_texts.append(text)

    valid_mask = np.array(valid_mask)

    if not processed_texts:
        return np.array([]), valid_mask

    try:
        outputs = llm.embed(processed_texts)
        embeddings = np.array([out.outputs.embedding for out in outputs], dtype=np.float32)
        return embeddings, valid_mask
    except Exception as e:
        logger.error(f'Error generando embeddings: {e}')
        return np.array([]), np.zeros(len(texts), dtype=bool)

def load_or_compute_persona_embeddings(
    llm: LLM,
    tokenizer,
    config: dict
) -> Tuple[List[str], np.ndarray]:
    """
    Cargar embeddings desde cache o calcularlos desde el parquet fuente definido en config.
    """
    embeddings_path = Path(config['embeddings_pkl_path'])
    batch_size = config['batch_size']
    max_model_len = config['max_model_len']

    # 1. Intentar cargar embeddings YA calculados (cache)
    if embeddings_path.exists():
        with log_time(f'Carga de embeddings cacheados desde {embeddings_path}'):
            try:
                with open(embeddings_path, 'rb') as f:
                    data = pickle.load(f)

                # Verificación estricta de formato
                if isinstance(data, dict) and 'personas' in data and 'embeddings' in data:
                    personas = data['personas']
                    persona_embeddings = data['embeddings']
                    logger.info(f'Embeddings recuperados: {len(personas)} personas')
                    return personas, persona_embeddings
                else:
                    logger.warning(f'El archivo {embeddings_path} existe pero no tiene formato correcto. Se recalculará.')
            except Exception as e:
                logger.warning(f'Error leyendo cache: {e}. Se recalculará.')

    # 2. Si no hay cache válido, calcular desde cero
    logger.info('Calculando embeddings nuevos...')

    # Cargar fuente (Input)
    source_path = Path(config.get('personas_source_path', ''))

    if source_path.exists() and source_path.suffix == '.parquet':
        with log_time(f'Carga de dataset fuente: {source_path}'):
            df_source = pl.read_parquet(source_path)
            # Asumimos columna 'character'
            if 'character' in df_source.columns:
                personas = df_source['character'].to_list()
            else:
                raise ValueError(f"La columna 'character' no existe en {source_path}. Columnas: {df_source.columns}")
            logger.info(f'Personas cargadas desde Parquet: {len(personas)}')
    else:
        # Fallback antiguo por si acaso
        logger.warning(f"No se encontró parquet fuente en: {source_path}. Intentando fallback a HF...")
        from datasets import load_dataset
        persona_dataset = load_dataset('proj-persona/PersonaHub', data_files='persona.jsonl')['train']
        personas = persona_dataset['persona']

    # Calcular embeddings en batches
    persona_embeddings_list = []
    for i in tqdm(range(0, len(personas), batch_size), desc='Calculando embeddings de personas'):
        batch = personas[i:i+batch_size]
        batch_embeddings, _ = get_embeddings_batch(llm, batch, tokenizer, max_model_len)
        persona_embeddings_list.append(batch_embeddings)

    if persona_embeddings_list:
        persona_embeddings = np.vstack(persona_embeddings_list).astype(np.float32)
    else:
        persona_embeddings = np.array([], dtype=np.float32)

    logger.info(f'Dimensiones embeddings calculados: {persona_embeddings.shape}')

    # Guardar Cache (Output)
    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(embeddings_path, 'wb') as f:
        pickle.dump({'personas': personas, 'embeddings': persona_embeddings}, f)
    logger.info(f'Cache guardado en: {embeddings_path}')

    return personas, persona_embeddings

def process_batch(
    batch_df: pl.DataFrame,
    llm: LLM,
    tokenizer,
    max_model_len: int,
    persona_embeddings: np.ndarray,
    personas: List[str],
    chunk_column: str
) -> List[Dict]:
    """Procesar un batch de chunks"""
    batch_texts = batch_df[chunk_column].to_list()

    batch_embeddings, valid_mask = get_embeddings_batch(llm, batch_texts, tokenizer, max_model_len)

    if len(batch_embeddings) == 0 or not np.any(valid_mask):
        return []

    batch_df_filtered = batch_df.filter(pl.Series(valid_mask))

    similarities_matrix = cosine_similarity(
        batch_embeddings.astype(np.float32),
        persona_embeddings.astype(np.float32)
    )

    top5_indices = np.argpartition(similarities_matrix, -5, axis=1)[:, -5:]
    for i in range(len(top5_indices)):
        top5_indices[i] = top5_indices[i][np.argsort(similarities_matrix[i, top5_indices[i]])[::-1]]

    results = []
    batch_rows = batch_df_filtered.to_dicts()

    for j, row in enumerate(batch_rows):
        top5_idx = top5_indices[j]
        top5_scores = similarities_matrix[j, top5_idx]

        results.append({
            'id_chunk': row.get('id_chunk', row.get('id', None)),
            'id_document': row.get('id_document', None),
            'passage': row[chunk_column],
            'character': '\n'.join([personas[idx] for idx in top5_idx]),
            'top_5_scores': json.dumps(top5_scores.tolist()),
            'source_id': row.get('source_id', None)
        })

    return results

def write_results_batch(results: List[Dict], output_path: Path, temp_dir: Path, offset: int, is_first: bool):
    if not results:
        return
    df_temp = pl.DataFrame(results)
    if is_first:
        df_temp.write_parquet(output_path)
    else:
        temp_file = temp_dir / f"temp_{offset}.parquet"
        df_temp.write_parquet(temp_file)

def consolidate_parquet_files(output_path: Path, temp_dir: Path):
    temp_files = sorted(temp_dir.glob("temp_*.parquet"))
    if not temp_files:
        return

    logger.info(f'Consolidando {len(temp_files)} archivos temporales...')
    all_lazyframes = []
    if output_path.exists():
        all_lazyframes.append(pl.scan_parquet(output_path))
    all_lazyframes.extend([pl.scan_parquet(str(f)) for f in temp_files])

    df_final = pl.concat(all_lazyframes).collect()
    df_final.write_parquet(output_path)

    for temp_file in temp_files:
        try:
            temp_file.unlink()
        except Exception:
            pass

def process_parquet_file(
    parquet_path: Path,
    output_dir: Path,
    llm: LLM,
    tokenizer,
    personas: List[str],
    persona_embeddings: np.ndarray,
    config: dict
) -> Optional[Path]:
    base_filename = parquet_path.stem
    temp_dir = output_dir / f"{base_filename}_temp"
    output_path = output_dir / f"{base_filename}_with_persona.parquet"

    logger.info(f'PROCESANDO: {parquet_path.name}')

    if output_path.exists():
        logger.warning(f'Archivo ya existe. SALTANDO: {output_path}')
        return None

    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        total_rows = pl.scan_parquet(parquet_path).filter(pl.col("valid")).select(pl.len()).collect().item()
    except Exception as e:
        logger.error(f'Error leyendo parquet: {e}')
        return None

    chunk_column = 'chunk'
    batch_size = config['batch_size']
    write_batch_size = config['write_batch_size']
    parquet_chunk_size = batch_size * 10

    results_buffer = []
    first_write = True
    lf = pl.scan_parquet(parquet_path).filter(pl.col("valid"))

    with tqdm(total=total_rows, desc=f'📄 {base_filename}', unit='rows') as pbar:
        for offset in range(0, total_rows, parquet_chunk_size):
            try:
                df_chunk = lf.slice(offset, parquet_chunk_size).collect()
                for i in range(0, len(df_chunk), batch_size):
                    batch_df = df_chunk[i:i+batch_size]

                    try:
                        batch_results = process_batch(
                            batch_df, llm, tokenizer, config['max_model_len'],
                            persona_embeddings, personas, chunk_column
                        )
                        results_buffer.extend(batch_results)
                    except Exception as e:
                        logger.error(f'Error en batch: {e}')

                    if len(results_buffer) >= write_batch_size:
                        write_results_batch(results_buffer, output_path, temp_dir, offset, first_write)
                        first_write = False
                        results_buffer = []
                        gc.collect()

                    pbar.update(len(batch_df))

                del df_chunk
                gc.collect()

            except Exception as e:
                logger.error(f'Error chunk offset {offset}: {e}')
                continue

    if results_buffer:
        write_results_batch(results_buffer, output_path, temp_dir, -1, first_write)

    consolidate_parquet_files(output_path, temp_dir)

    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    return output_path

def main():
    config = load_config()
    setup_environment(config)

    # Buscar archivos a procesar
    parquet_files = sorted(glob.glob(config['parquet_path']))
    if not parquet_files:
        logger.error(f'No se encontraron archivos en: {config["parquet_path"]}')
        return 1

    llm = initialize_llm(config)
    tokenizer = llm.get_tokenizer()

    # Cargar embeddings usando la nueva función que lee del config
    personas, persona_embeddings = load_or_compute_persona_embeddings(llm, tokenizer, config)

    output_dir = Path(config['output_path'])
    output_dir.mkdir(parents=True, exist_ok=True)

    for parquet_path in parquet_files:
        process_parquet_file(
            Path(parquet_path), output_dir, llm, tokenizer,
            personas, persona_embeddings, config
        )

    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception(f'Error fatal: {e}')
        sys.exit(1)