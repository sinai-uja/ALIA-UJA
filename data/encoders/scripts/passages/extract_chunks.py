import os, yaml, sys, argparse, glob
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
import polars as pl
from tqdm import tqdm
import datetime
from pathlib import Path
import multiprocessing as mp

from langchain_huggingface import HuggingFaceEmbeddings

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import the new SemanticChunker class
from semantic_chunker import SemanticChunker  # Make sure this file is in your project directory

try:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    logger.info(f"Configuración cargada correctamente desde {config_path}")
except FileNotFoundError as e:
    logger.exception(f"No se encontró el archivo config.yaml: {e}")
    sys.exit(1)
except yaml.YAMLError as e:
    logger.exception(f"Error al parsear el archivo config.yaml: {e}")
    sys.exit(1)

# Set spawn method for CUDA compatibility - Must be called before any CUDA operations
if __name__ == "__main__":
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass  # Already set

import torch
logger.info(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    logger.info(f"CUDA device: {torch.cuda.get_device_name(0)}")

def get_model():
    """Inicializa el modelo de embeddings y el SemanticChunker optimizado."""
    try:
        # Initialize embedding model
        device = "cuda" if torch.cuda.is_available() else "cpu"
        embedding_model = HuggingFaceEmbeddings(
            model_name=config['splitter']['embedding_model'],
            model_kwargs={
                "device": device,
                "trust_remote_code": config['splitter'].get('trust_remote_code', True)
            },
            encode_kwargs={
                "normalize_embeddings": config['splitter'].get('normalize_embeddings', True),
                "batch_size": config['splitter'].get('embedding_batch_size', 32)
            }
        )
        
        # Determine if parallel processing should be used
        # IMPORTANT: Disable parallel processing when using GPU to avoid CUDA fork issues
        max_workers = config['splitter'].get('max_workers', None)
        if torch.cuda.is_available() and max_workers and max_workers > 1:
            logger.warning("GPU detectada: Deshabilitando procesamiento paralelo para evitar conflictos CUDA")
            max_workers = 1  # Disable parallelization with GPU

        
        # Initialize the optimized SemanticChunker
        chunker = SemanticChunker(
            embeddings=embedding_model,
            buffer_size=config['splitter'].get('buffer_size', 1),
            add_start_index=config['splitter'].get('add_start_index', False),
            breakpoint_threshold_type=config['splitter'].get('breakpoint_threshold_type', 'percentile'),
            breakpoint_threshold_amount=config['splitter'].get('breakpoint_threshold_amount', None),
            number_of_chunks=config['splitter'].get('number_of_chunks', None),
            sentence_split_regex=config['splitter'].get('sentence_split_regex', None),
            min_chunk_size_tokens=config['splitter'].get('min_chunk_size_tokens', 512),
            max_chunk_size_tokens=config['splitter'].get('max_chunk_size_tokens', 1024),
            embedding_batch_size=config['splitter'].get('embedding_batch_size', 32),
            use_spacy=config['splitter'].get('use_spacy', True),
            spacy_model=config['splitter'].get('spacy_model', 'en_core_web_sm'),
            tokenizer_model=config['splitter'].get('tokenizer_model', 'cl100k_base'),
            max_workers=max_workers,
            enable_chunk_balancing=config['splitter'].get('enable_chunk_balancing', True),
            target_chunk_variance=config['splitter'].get('target_chunk_variance', 0.2)
        )
        
        logger.info(f"SemanticChunker inicializado correctamente con modelo {config['splitter']['embedding_model']}")
        logger.info(f"Configuración: min_tokens={config['splitter'].get('min_chunk_size_tokens', 512)}, "
                   f"max_tokens={config['splitter'].get('max_chunk_size_tokens', 1024)}, "
                   f"batch_size={config['splitter'].get('embedding_batch_size', 32)}, "
                   f"use_spacy={config['splitter'].get('use_spacy', True)}, "
                   f"device={device}, max_workers={max_workers}")
        
        return chunker

    except Exception as e:
        logger.exception(f"Error al inicializar el SemanticChunker: {e}")
        sys.exit(1)

def _filter_chunks(chunks: list[dict]) -> list[dict]:
    """Filtra los chunks según criterios de puntuación.
    
    Args:
        chunks: List of chunk dictionaries with 'text', 'tokens', and 'valid' keys
        
    Returns:
        Filtered list of chunk dictionaries
    """
    filtered_chunks = []
    for chunk_dict in chunks:
        chunk_text = chunk_dict['text']
        # Filtro de puntuación
        points = chunk_text.count('.')
        percentage = points / len(chunk_text) if len(chunk_text) > 0 else 0
        if percentage < config['splitter'].get('chunk_punctuation_percentage', 0.1):
            filtered_chunks.append(chunk_dict)
    return filtered_chunks

def chunk_with_splitter(model: SemanticChunker, text: str) -> list[dict]:
    """Divide texto en chunks usando el SemanticChunker optimizado.
    
    Returns:
        List of chunk dictionaries with 'text', 'tokens', and 'valid' keys
    """
    try:
        chunks = model.split_text(text)  # Returns list of dicts with 'text', 'tokens', 'valid'
        # Filtro de calidad de chunk
        filtered_chunks = _filter_chunks(chunks)
        
        # Log statistics
        if filtered_chunks:
            valid_chunks = [c for c in filtered_chunks if c['valid']]
            invalid_chunks = [c for c in filtered_chunks if not c['valid']]
            chunk_tokens = [c['tokens'] for c in filtered_chunks]
            if chunk_tokens:
                logger.debug(f"Chunks generados: {len(filtered_chunks)} "
                           f"(válidos: {len(valid_chunks)}, inválidos: {len(invalid_chunks)}), "
                           f"Tokens promedio: {sum(chunk_tokens)/len(chunk_tokens):.0f}")
        
        return filtered_chunks
    except Exception as e:
        logger.exception(f"Error al dividir texto con SemanticChunker: {e}")
        return []

def get_chunks(documents: list = [], ids: list = [], source: str = ""):
    """Genera chunks para una lista de documentos usando procesamiento paralelo."""
    
    document_ids, chunks, chunks_ids, tokens_list, valid_list = [], [], [], [], []

    try:
        model = get_model()
        
        # Adjust buffer size based on number of documents
        if len(documents) > config['splitter'].get('max_docs', 1000):
            model.buffer_size = config['splitter'].get('buffer_size', 1) * 2
            logger.info(f"Buffer size aumentado a {model.buffer_size} debido al alto número de documentos ({len(documents)})")
        else:
            model.buffer_size = config['splitter'].get('buffer_size', 1)

        interval = max(1, len(documents) / 1000)
        j = 1
        
        # Check if parallel processing is enabled and beneficial
        use_parallel = (
            len(documents) > 1 and 
            config['splitter'].get('max_workers', None) is not None and
            config['splitter'].get('max_workers', 0) > 1
        )
        
        if use_parallel:
            logger.info(f"Usando procesamiento paralelo con {config['splitter'].get('max_workers')} workers")
            # Use the built-in parallel processing of SemanticChunker
            from langchain_core.documents import Document
            
            # Create Document objects
            lang_documents = [
                Document(page_content=doc, metadata={"id": ids[i]})
                for i, doc in enumerate(documents)
            ]
            
            # Process in parallel
            split_documents = model.split_documents(lang_documents)
            
            # Extract results
            for doc in tqdm(split_documents, total=len(split_documents), desc="Procesando documentos"):
                
                original_id = doc.metadata["id"]
                chunk_text = doc.page_content
                chunk_tokens = doc.metadata.get("tokens", 0)
                chunk_valid = doc.metadata.get("valid", True)
                
                # Apply punctuation filter
                points = chunk_text.count('.')
                percentage = points / len(chunk_text) if len(chunk_text) > 0 else 0
                if percentage < config['splitter'].get('chunk_punctuation_percentage', 0.1):
                    chunks.append(chunk_text)
                    document_ids.append(original_id)
                    tokens_list.append(chunk_tokens)
                    valid_list.append(chunk_valid)
                    
                    # Format chunk ID
                    base_id = original_id.replace(" ", "_")
                    if "\\" in original_id:
                        file_part = original_id.split("\\")[-1].replace(" ", "_")
                        doc_id = f"{source}-{file_part}"
                    else:
                        doc_id = f"{source}-{base_id}"
                    
                    chunks_ids.append(f"{doc_id}-{j}")
                    j += 1
        else:
            # Serial processing (original method)
            logger.info("Usando procesamiento serial")
            for i, doc in enumerate(tqdm(documents, desc="Procesando documentos", total=len(documents), miniters=interval)):
                _chunks = chunk_with_splitter(model, doc)  # Returns list of dicts
                n_chunks = len(_chunks)
                
                # Extract data from chunk dictionaries
                for chunk_dict in _chunks:
                    chunks.append(chunk_dict['text'])
                    tokens_list.append(chunk_dict['tokens'])
                    valid_list.append(chunk_dict['valid'])
                
                document_ids.extend([ids[i]] * n_chunks)

                # Document ID procesado y formateado una sola vez
                base_id = ids[i].replace(" ", "_")
                if "\\" in ids[i]:
                    file_part = ids[i].split("\\")[-1].replace(" ", "_")
                    doc_id = f"{source}-{file_part}"
                else:
                    doc_id = f"{source}-{base_id}"
                
                # Simple comprensión para los chunk_ids
                chunks_ids.extend([f"{doc_id}-{k}" for k in range(j, j + n_chunks)])
                j += n_chunks

        logger.info(f"Generados {len(chunks)} chunks para {len(documents)} documentos.")
        logger.info(f"Chunks válidos: {sum(valid_list)}, Chunks inválidos: {len(valid_list) - sum(valid_list)}")
        
        # Memory cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.debug("GPU memory cache cleared")

    except Exception as e:
        logger.exception(f"Error al generar los chunks: {e}")

    return document_ids, chunks, chunks_ids, tokens_list, valid_list

def aggregate_chunks(corpus: str) -> pl.DataFrame | None:
    """Agrega todos los archivos Parquet de un corpus en un único archivo parquet de salida."""
    try:
        base_path = Path(config['chunk_path_dir']) / corpus
        parquet_files = list(base_path.glob('*.parquet'))
        if not parquet_files:
            raise FileNotFoundError(f"No se encontraron ficheros parquet en {base_path}")

        logger.info(f"Agregando {len(parquet_files)} archivos parquet...")

        # Escaneo eficiente de todos los parquet usando LazyFrame
        df = pl.scan_parquet(parquet_files).collect(streaming=True)

        # Guarda el resultado con compresión Zstd (alta eficiencia)
        output_path = base_path.parent / f"{corpus}.parquet"
        df.write_parquet(output_path, compression='zstd')
        
        logger.info(f"Agregación completada: {len(df)} chunks guardados en {output_path}")

        return df

    except Exception:
        logger.exception(f"Error al agregar los ficheros de chunks del corpus '{corpus}'")
        return None

def _get_statictics(source: str, df: pl.DataFrame):
    """Muestra estadísticas de los chunks basadas en tokens."""
    
    print(f"{source} - {df.columns}")
    print(f"\t{df.shape[0]} chunks, para {len(df['id_document'].unique().to_list())} documentos")

    # Estadísticas de tokens
    if 'tokens' in df.columns:
        mean_tokens = df['tokens'].mean()
        min_tokens = df['tokens'].min()
        max_tokens = df['tokens'].max()
        median_tokens = df['tokens'].median()
        print(f"\tTamaño de chunks (tokens) - Media: {mean_tokens:.2f}, Mínimo: {min_tokens}, Máximo: {max_tokens}, Mediana: {median_tokens}")
    
    # Estadísticas de validez
    if 'valid' in df.columns:
        valid_count = df['valid'].sum()
        invalid_count = df.shape[0] - valid_count
        print(f"\tChunks válidos: {valid_count}, Chunks inválidos: {invalid_count}")
    
    # Estadísticas de longitud de caracteres (opcional, para referencia)
    chunk_lengths = df.select(pl.col('chunk').str.len_chars())
    mean_length = chunk_lengths['chunk'].mean()
    min_length = chunk_lengths['chunk'].min()
    max_length = chunk_lengths['chunk'].max()
    median_length = chunk_lengths['chunk'].median()
    print(f"\tTamaño de chunks (caracteres) - Media: {mean_length:.2f}, Mínimo: {min_length}, Máximo: {max_length}, Mediana: {median_length}")

    with pl.Config(fmt_str_lengths=200, tbl_rows=10):
        print(df.sample(min(10, df.shape[0])))


def main(args):

    logger.info(f"Iniciando procesamiento del corpus '{args.corpus}'")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Hora de inicio: {timestamp}")

    # 1. Dividir por dataset
    try:
        # ficheros parquet
        files = glob.glob(os.path.join(config['corpus_path'], args.corpus, "*_enriched.parquet"))
        files.sort()
        # nombres de los datasets
        unique_sources = [file.replace("_enriched.parquet", "") for file in files]
        unique_sources.sort()
        logger.info(f"Fuentes encontradas: {len(unique_sources)}")
    except Exception as e:
        logger.exception(f"Error al extraer sources del corpus: {e}")
        sys.exit(1)

    output_path_dir = os.path.join(
        config['chunk_path_dir'],
        args.corpus
    )
    os.makedirs(output_path_dir, exist_ok=True)
    
    files = [
        os.path.join(config['corpus_path'], args.corpus, f"{args.dataset}_enriched.parquet")
    ]
    unique_sources = [args.dataset]
    
    skip_sources = [
        'EuroPat'
    ]

    # 2. Obtener chunks por dataset
    for idx, file in enumerate(tqdm(files, total=len(files), desc="Processing sources")):

        try:
            
            source = unique_sources[idx]
            print(f"{source}: from file '{file}'")
                        
            output_path = os.path.join(config['chunk_path_dir'], args.corpus, f"{source}.parquet")

            if (os.path.exists(output_path) and not args.FORCE):
                logger.warning(f"Chunks for source '{source}' already exist at {output_path}. Skipping...")
                continue
            if source in skip_sources:
                logger.warning(f"Source '{source}' is in the skip list. Skipping...")
                continue

            source_corpus = pl.read_parquet(file)
            print(source_corpus.shape)
            with pl.Config(fmt_str_lengths=400, tbl_rows=2):
                print(source_corpus.head(2))
            source_ids = source_corpus['id'].to_list()
            source_documents = source_corpus['text'].to_list()

            logger.info(f"Procesando source '{source}' con {len(source_documents)} documentos.")

            document_ids, chunks, chunks_ids, tokens_list, valid_list = get_chunks(
                documents=source_documents, 
                ids=source_ids, 
                source=source
            )

            if not chunks:
                logger.warning(f"No se generaron chunks para source '{source}'")
                continue

            df_chunks = pl.DataFrame({
                "source_id": [source] * len(chunks),
                "id_document": document_ids,
                "id_chunk": chunks_ids,
                "chunk": chunks,
                "tokens": tokens_list,
                "valid": valid_list
            })

            df_chunks.write_parquet(output_path)
            # print results for debugging
            _get_statictics(source, df_chunks)
            logger.info(f"Chunks para source '{source}' guardados en {output_path} ({len(chunks)} chunks)")

        except Exception as e:
            logger.exception(f"Error procesando source '{source}': {e}")
   
    timestamp_end = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Procesamiento completado. Hora de finalización: {timestamp_end}")

class VandelviraChunksArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_help()
        print("\nERROR:", message, file=sys.stderr)
        print("\nAdditional details:")
        print("- Use --corpus <identifier> to process an specific corpus.")
        print("- Use --dataset <identifier> to process an specific dataset.")
        print("- Use --FORCE to force the splitting process.")

        self.exit(2)

if __name__ == "__main__":

    parser = VandelviraChunksArgumentParser(description="Process corpus with optimized SemanticChunker.")
    parser.add_argument('--corpus', type=str, required=True, help="Identifier of the corpus to split.")
    parser.add_argument('--dataset', type=str, required=True, help="Identifier of the dataset to split.")
    parser.add_argument('--FORCE', action='store_true', help="Force the splitting process.")

    args = parser.parse_args()

    main(args)
