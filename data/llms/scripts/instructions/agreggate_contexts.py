"""
Script para combinar chunks de texto con sus headers correspondientes.

Este módulo procesa dos archivos parquet (chunks y headers), los une por documento,
concatena el header con cada chunk para crear contexto enriquecido, y calcula 
el número de tokens de cada contexto.
"""

import logging, os
import polars as pl
import tiktoken
import yaml
from pathlib import Path
from typing import Dict, Any

def setup_logging(log_level: str = "INFO") -> None:
    """
    Configura el sistema de logging para la aplicación.
    
    Args:
        log_level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    Carga la configuración desde archivo YAML.
    
    Args:
        config_path: Ruta al archivo de configuración
        
    Returns:
        Diccionario con la configuración cargada
        
    Raises:
        FileNotFoundError: Si el archivo de configuración no existe
        yaml.YAMLError: Si hay errores en el formato YAML
    """
    logger = logging.getLogger(__name__)
    
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        logger.info(f"Configuración cargada correctamente desde {config_path}")
        logger.debug(f"Configuración: {config}")
        
        return config
    
    except yaml.YAMLError as e:
        logger.error(f"Error al parsear el archivo YAML: {e}")
        raise
    except Exception as e:
        logger.error(f"Error inesperado al cargar configuración: {e}")
        raise


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """
    Calcula el número de tokens de un texto usando tiktoken.
    
    Args:
        text: Texto para contar tokens
        encoding_name: Nombre del encoding a utilizar (por defecto cl100k_base para GPT-4)
        
    Returns:
        Número de tokens en el texto
    """
    if not text or not isinstance(text, str):
        return 0
    
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        num_tokens = len(encoding.encode(text))
        return num_tokens
    except Exception as e:
        logging.getLogger(__name__).warning(f"Error al contar tokens: {e}. Retornando 0.")
        return 0


def load_parquet_files(chunks_path: str, headers_path: str, readme_file: str) -> tuple:
    """
    Carga los archivos parquet de chunks y headers.
    
    Args:
        chunks_path: Ruta al archivo parquet de chunks
        headers_path: Ruta al archivo parquet de headers
        
    Returns:
        Tupla con (df_chunks, df_headers)
        
    Raises:
        FileNotFoundError: Si alguno de los archivos no existe
    """
    logger = logging.getLogger(__name__)
    
    # Validar que existen los archivos
    if not Path(chunks_path).exists():
        raise FileNotFoundError(f"Archivo de chunks no encontrado: {chunks_path}")
    if not Path(headers_path).exists():
        raise FileNotFoundError(f"Archivo de headers no encontrado: {headers_path}")
    
    # Cargar chunks
    logger.info(f"Cargando chunks desde {chunks_path}")
    df_chunks = pl.read_parquet(chunks_path)
    logger.info(f"Chunks cargados: {df_chunks.shape[0]} filas, {df_chunks.shape[1]}")
    logger.debug(f"Columnas del DataFrame de chunks: {df_chunks.columns}")
    
    # Cargar headers
    logger.info(f"Cargando headers desde {headers_path}")
    df_headers = pl.read_parquet(headers_path)
    logger.info(f"Headers cargados: {df_headers.shape[0]} filas, {df_headers.shape[1]}")
    # ! columnas 'tokens' y 'valid'
    # Paso 1: Crear la columna 'tokens'
    _df = df_headers.with_columns([
        pl.col('header')
        .map_elements(lambda x: count_tokens(x, 'cl100k_base'), return_dtype=pl.Int64)
        .alias('tokens')
    ])
    # Paso 2: Crear la columna 'valid' usando la columna 'tokens'
    df_headers = _df.with_columns([
        (pl.col('tokens') < 500).alias('valid')
    ])
    os.remove(headers_path)
    df_headers.write_parquet(headers_path)
    logger.debug(f"Columnas del DataFrame de headers: {df_headers.columns}")
    
    if readme_file:
        try:
            entry = f"N chunks originales: {df_chunks.shape[0]}\n"
            entry += f"N headers originales: {df_headers.shape[0]}"
            with open(readme_file, 'a', encoding='utf-8') as file:
                file.write(f"{entry}\n")
            logger.info(f"Estadísticas añadidas al archivo {readme_file}")
        except Exception as e:
            logger.warning(f"No se pudo escribir en el archivo {readme_file}: {e}")
    
    return df_chunks, df_headers


def validate_dataframes(
    df_chunks: pl.DataFrame, 
    df_headers: pl.DataFrame,        
    require_valid_column: bool = False
) -> None:
    """
    Valida que los DataFrames tienen las columnas requeridas.
    
    Args:
        df_chunks: DataFrame de chunks
        df_headers: DataFrame de headers
        require_valid_column: Si True, requiere que exista la columna 'valid'
        
    Raises:
        ValueError: Si faltan columnas requeridas
    """
    logger = logging.getLogger(__name__)

    # Validar columnas de chunks
    required_chunks_cols = ['source_id', 'id_document', 'id_chunk', 'chunk']
    # Añadir 'valid' como columna requerida si se especifica
    if require_valid_column:
        required_chunks_cols.append('valid')
    missing_chunks = [col for col in required_chunks_cols if col not in df_chunks.columns]
    if missing_chunks:
        raise ValueError(f"Faltan columnas en el DataFrame de chunks: {missing_chunks}")

    # Validar columnas de headers
    required_headers_cols = ['source_id', 'id', 'header', 'classification']
    if require_valid_column:
        required_headers_cols.append('valid')
    missing_headers = [col for col in required_headers_cols if col not in df_headers.columns]
    if missing_headers:
        raise ValueError(f"Faltan columnas en el DataFrame de headers: {missing_headers}")

    # Si existe la columna 'valid' en df_chunks, validar su tipo
    if 'valid' in df_chunks.columns:
        valid_dtype = df_chunks['valid'].dtype
        if valid_dtype != pl.Boolean:
            logger.warning(f"La columna 'valid' de df_chunks tiene tipo {valid_dtype} en lugar de Boolean. "
                           f"Podría causar problemas en el filtrado.")
        value_counts = df_chunks.group_by('valid').agg(pl.len().alias('count'))
        logger.debug(f"Distribución de valores en columna 'valid' (chunks):\n{value_counts}")

    # Si existe la columna 'valid' en df_headers, validar su tipo
    if 'valid' in df_headers.columns:
        valid_dtype = df_headers['valid'].dtype
        if valid_dtype != pl.Boolean:
            logger.warning(f"La columna 'valid' de df_headers tiene tipo {valid_dtype} en lugar de Boolean. "
                           f"Podría causar problemas en el filtrado.")
        value_counts = df_headers.group_by('valid').agg(pl.len().alias('count'))
        logger.debug(f"Distribución de valores en columna 'valid' (headers):\n{value_counts}")

    logger.info("Validación de DataFrames completada exitosamente")


def prepare_headers_dataframe(df_headers: pl.DataFrame) -> pl.DataFrame:
    """
    Prepara el DataFrame de headers seleccionando y renombrando columnas necesarias.
    
    Args:
        df_headers: DataFrame original de headers
        
    Returns:
        DataFrame de headers con columnas relevantes y nombres correctos
    """
    logger = logging.getLogger(__name__)
    
    # Seleccionar solo las columnas necesarias y renombrar 'id' a 'id_document'
    df_headers_clean = df_headers.select([
        pl.col('source_id'),
        pl.col('id').alias('id_document'),
        pl.col('header'),
        pl.col('classification'),
        pl.col('tokens'),
        pl.col('valid')
    ])
    
    logger.debug(f"Headers preparado con columnas: {df_headers_clean.columns}")
    
    return df_headers_clean


def join_chunks_with_headers(
    df_chunks: pl.DataFrame, 
    df_headers: pl.DataFrame,
    join_type: str = "left",
    validation_value: bool = True
) -> pl.DataFrame:
    """
    Une los DataFrames de chunks y headers basándose en source_id e id_document.
    Filtra los chunks según el valor de la columna 'valid'.
    
    Args:
        df_chunks: DataFrame de chunks
        df_headers: DataFrame de headers (ya preparado)
        join_type: Tipo de join a realizar (left, inner, etc.)
        validation_value: Valor booleano para filtrar la columna 'valid' (True o False)
        
    Returns:
        DataFrame unido con todas las columnas necesarias, filtrado por validación
    """
    logger = logging.getLogger(__name__)
    
    # Verificar si existe la columna 'valid' en el DataFrame de chunks
    if 'valid' not in df_chunks.columns:
        logger.warning(f"La columna 'valid' no existe en el DataFrame de chunks. {df_chunks.columns}"
                      "Se procederá sin filtrar por validación.")
        df_chunks_filtered = df_chunks
    if 'valid' not in df_headers.columns:
        logger.warning(f"La columna 'valid' no existe en el DataFrame de headers. {df_headers.columns}"
                      "Se procederá sin filtrar por validación.")
        df_headers_filtered = df_headers
    
    if 'valid' in df_chunks.columns and 'valid' in df_headers.columns:
        # Contar registros antes del filtrado
        total_chunks = df_chunks.shape[0]
        total_headers = df_headers.shape[0]
        
        # Filtrar chunks según el valor de validación
        logger.info(f"Filtrando chunks donde 'valid' == {validation_value}")
        df_chunks_filtered = df_chunks.filter(pl.col('valid') == validation_value)
        filtered_chunks = df_chunks_filtered.shape[0]
        removed_chunks = total_chunks - filtered_chunks
        logger.info(f"Chunks después del filtrado: {filtered_chunks} "
                   f"({removed_chunks} chunks eliminados, "
                   f"{(removed_chunks/total_chunks*100):.2f}% del total)")
        
        # Filtrar headers según el valor de validación
        logger.info(f"Filtrando headers donde 'valid' == {validation_value}")
        df_headers_filtered = df_headers.filter(pl.col('valid') == validation_value)
        filtered_headers = df_headers_filtered.shape[0]
        removed_headers = total_headers - filtered_headers
        logger.info(f"Headers después del filtrado: {filtered_headers} "
                   f"({removed_headers} headers eliminados, "
                   f"{(removed_headers/total_headers*100):.2f}% del total)")
        
        # Advertir si se eliminaron todos los chunks
        if filtered_chunks == 0:
            logger.warning(f"⚠️  ADVERTENCIA: El filtrado por 'valid' == {validation_value} "
                          f"eliminó TODOS los chunks. El resultado estará vacío.")
    
    logger.info(f"Realizando {join_type} join entre chunks y headers")
    logger.debug(f"Join keys: source_id, id_document")
    
    # Realizar el join en múltiples columnas
    df_joined = df_chunks_filtered.join(
        df_headers_filtered,
        on=['source_id', 'id_document'],
        how=join_type
    )
    
    logger.info(f"Join completado: {df_joined.shape[0]} filas resultantes")
    
    # Verificar si hay valores nulos en header (chunks sin header asociado)
    if df_joined.shape[0] > 0:
        null_headers = df_joined.filter(pl.col('header').is_null()).shape[0]
        if null_headers > 0:
            logger.warning(f"Se encontraron {null_headers} chunks sin header asociado")
    
    return df_joined

def _statistics(df, readme_file, logger):
    
    # Estadísticas de tokens
    token_stats = df.select([
        pl.col('tokens').min().alias('min'),
        pl.col('tokens').max().alias('max'),
        pl.col('tokens').mean().alias('mean'),
        pl.col('tokens').median().alias('median')
    ])
    
    # Extra: add line to file.txt which path is in config['readme-file'].format(domain=config['domain']) like {'tam': número de contextos, 'min': min, 'max': max, 'mean': mean, 'median': median}
    if readme_file:
        try:
            stats = token_stats.to_dicts()[0]
            stats['tam'] = df.shape[0]
            with open(readme_file, 'a', encoding='utf-8') as file:
                file.write(f"{stats}\n\n")
            logger.info(f"Estadísticas añadidas al archivo {readme_file}")
        except Exception as e:
            logger.warning(f"No se pudo escribir en el archivo {readme_file}: {e}")
    
    logger.info(f"Estadísticas de tokens: {token_stats.to_dicts()[0]}")


def create_context_and_tokens(
    df: pl.DataFrame,
    separator: str = "\n\n",
    encoding_name: str = "cl100k_base",
    readme_file: str = "file.txt"
) -> pl.DataFrame:
    """
    Crea la columna 'context' concatenando header y chunk, y calcula tokens.
    
    Args:
        df: DataFrame unido
        separator: Separador entre header y chunk
        encoding_name: Nombre del encoding para tiktoken
        
    Returns:
        DataFrame con las columnas 'context' y 'tokens' añadidas
    """
    logger = logging.getLogger(__name__)
    
    logger.info("Creando columna 'context' concatenando header + chunk")
    
    # Crear la columna context concatenando header y chunk
    df_with_context = df.with_columns([
        (pl.col('header').fill_null("") + pl.lit(separator) + pl.col('chunk').fill_null(""))
        .alias('context')
    ])
    
    logger.info("Calculando tokens para cada contexto")
    
    # Calcular tokens para cada contexto
    # Nota: Para grandes volúmenes, esto puede ser lento. 
    # Considerar paralelización si es necesario.
    df_with_tokens = df_with_context.with_columns([
        pl.col('context')
        .map_elements(lambda x: count_tokens(x, encoding_name), return_dtype=pl.Int64)
        .alias('tokens')
    ])
    logger.info("Columnas 'context' y 'tokens' creadas exitosamente")
    
    _statistics(df_with_tokens, readme_file, logger)
    
    return df_with_tokens


def select_output_columns(df: pl.DataFrame) -> pl.DataFrame:
    """
    Selecciona y ordena las columnas finales del DataFrame de salida.
    
    Args:
        df: DataFrame completo
        
    Returns:
        DataFrame con las columnas en el orden especificado
    """
    logger = logging.getLogger(__name__)
    
    output_columns = [
        'source_id',
        'id_document',
        'id_chunk',
        'header',
        'chunk',
        'context',
        'tokens',
        'classification'
    ]
    
    df_output = df.select(output_columns)
    
    logger.info(f"DataFrame final con {df_output.shape[0]} filas y {df_output.shape[1]} columnas")
    logger.debug(f"Columnas finales: {df_output.columns}")
    
    return df_output


def save_output(df: pl.DataFrame, output_path: str, file_format: str = "parquet") -> None:
    """
    Guarda el DataFrame resultante en el formato especificado.
    
    Args:
        df: DataFrame a guardar
        output_path: Ruta donde guardar el archivo
        file_format: Formato del archivo (parquet, csv)
    """
    logger = logging.getLogger(__name__)
    
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Guardando resultado en {output_path} (formato: {file_format})")
    
    if file_format.lower() == "parquet":
        df.write_parquet(output_path)
        df.write_ndjson(output_path.replace("parquet", "jsonl"))
    elif file_format.lower() == "csv":
        df.write_csv(output_path)
    else:
        raise ValueError(f"Formato no soportado: {file_format}")
    
    logger.info(f"Archivo guardado exitosamente: {output_path}")
    
    # Información del archivo guardado
    file_size = output_file.stat().st_size / (1024 * 1024)  # MB
    logger.info(f"Tamaño del archivo: {file_size:.2f} MB")


def main(chunks_path, headers_path, output_path):
    """
    Función principal que orquesta todo el proceso.
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Cargar configuración
        config = load_config(os.path.join(os.path.dirname(__file__), 'config.yaml'))
        
        # Configurar logging según el nivel del config
        setup_logging(config.get('logging', {}).get('level', 'INFO'))
        
        logger.info("=" * 80)
        logger.info("INICIANDO PROCESO DE CREACIÓN DE CONTEXTOS")
        logger.info("=" * 80)
        
        # Extraer configuraciones
        output_format = config['output'].get('format', 'parquet')
        separator = config.get('processing', {}).get('separator', '\n\n')
        encoding_name = config.get('processing', {}).get('tiktoken_encoding', 'cl100k_base')
        join_type = config.get('processing', {}).get('join_type', 'left')
        
        # Nuevo: obtener el valor de validación del config
        validation_value = config.get('processing', {}).get('validation', True)
        require_valid_column = config.get('processing', {}).get('require_valid_column', False)
        logger.info(f"Configuración de validación: filtrar chunks donde valid == {validation_value}")
        
        if config['readme-file'].format(domain=config['domain']):
            try:
                source = output_path.split("/")[-1].replace(".parquet", "")
                with open(config['readme-file'].format(domain=config['domain']), 'a', encoding='utf-8') as file:
                    file.write(f"{source}\n")
                logger.info(f"Estadísticas añadidas al archivo {config['readme-file'].format(domain=config['domain'])}")
            except Exception as e:
                logger.warning(f"No se pudo escribir en el archivo {config['readme-file'].format(domain=config['domain'])}: {e}")

        tiktoken_dir = config['processing']['tiktoken_dir']
        os.environ["TIKTOKEN_CACHE_DIR"] = tiktoken_dir

        # 1. Cargar archivos parquet
        df_chunks, df_headers = load_parquet_files(chunks_path, headers_path, config['readme-file'].format(domain=config['domain']))
        
        # 2. Validar DataFrames
        validate_dataframes(df_chunks, df_headers, require_valid_column)
        
        # 3. Preparar DataFrame de headers
        df_headers_clean = prepare_headers_dataframe(df_headers)
        
        # 4. Realizar join
        df_joined = join_chunks_with_headers(
            df_chunks, 
            df_headers_clean, 
            join_type,
            validation_value
        )
        
        # 5. Crear context y calcular tokens
        df_with_context = create_context_and_tokens(df_joined, separator, encoding_name, config['readme-file'].format(domain=config['domain']))
        
        # 6. Seleccionar columnas finales
        df_final = select_output_columns(df_with_context)
        
        # 7. Guardar resultado
        save_output(df_final, output_path, output_format)
        
        logger.info("=" * 80)
        logger.info("PROCESO COMPLETADO EXITOSAMENTE")
        logger.info("=" * 80)
        
        return df_final
        
    except Exception as e:
        logger.error(f"Error crítico en el proceso: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    
    config = load_config(os.path.join(os.path.dirname(__file__), 'config.yaml'))
    for source in config['sources']:
        print(source)
        chunks_path = os.path.join(
            config['input']['chunks_path'].format(domain=config['domain']), 
            f"{source}.parquet"
        )
        headers_path = os.path.join(
            config['input']['headers_path'].format(domain=config['domain']), 
            f"{source}.parquet"
        )
        output_path = os.path.join(
            config['output']['path'].format(domain=config['domain']),  
            f"{source}.parquet"
        )
        main(chunks_path, headers_path, output_path)
