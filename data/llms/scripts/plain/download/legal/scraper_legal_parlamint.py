"""Consolidador de datos del Parlamento de Andalucía (ParlaMint).

Este módulo procesa archivos CSV de sesiones plenarias del Parlamento
de Andalucía y los consolida en un único archivo Parquet.

Los datos contienen:
    - Transcripciones de sesiones plenarias
    - Metadatos de fechas, números de pleno y legislatura

Example:
    Ejecución básica::

        python scraper_legal_parlamint.py

    Esto consolidará los CSVs encontrados y generará
    un archivo Parquet unificado.

Attributes:
    CSV_FOLDER (str): Ruta a la carpeta con CSVs de origen.

Note:
    Los datos son de acceso público a través del portal
    del Parlamento de Andalucía.
"""

import logging
import os
import re
import unicodedata

import polars as pl
import win32net
import yaml


class DataCollector:
    """Consolidador de datos de ParlaMint.

    Esta clase gestiona la consolidación de archivos CSV
    de sesiones plenarias en un único dataset Parquet.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        csv_folder: Ruta a la carpeta con CSVs de origen.
        parquet_path: Ruta al archivo Parquet de salida.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "ParlaMint_Andalucia"],
        ...     csv_folder="path/to/csvs"
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str],
        csv_folder: str
    ) -> None:
        """Inicializa el consolidador.

        Args:
            config_path: Ruta al archivo YAML de configuración.
            folders: Lista de carpetas para crear la estructura.
            csv_folder: Ruta a la carpeta con CSVs de origen.
        """
        # Cargar configuración
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)

        # Conectar disco de red
        try:
            win32net.NetUseAdd(None, 2, {
                'remote': config['disk_path'],
                'local': None,
                'password': config['password'],
                'username': config['user']
            })
        except win32net.error:
            pass  # Ya conectado

        # Estructura de carpetas
        self.dataset_folder = os.path.join(config['disk_path'], *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        # Rutas
        self.csv_folder = csv_folder
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # Logger
        self.logger = self.setup_logger()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] CSV folder: {csv_folder}")

    def consolidate_csvs(self) -> dict:
        """Consolida todos los archivos CSV del directorio en un único DataFrame Parquet.

        Itera sobre cada archivo `.csv` de `self.csv_folder`, lo lee con Polars,
        renombra columnas si las cabeceras siguen el esquema antiguo (`archivo`/`texto`),
        añade columna `section` con el nombre del archivo, normaliza la columna `id`
        a Unicode NFC y extrae metadatos de la sesión (fecha, número de pleno, legislatura)
        mediante expresiones regulares. Todos los DataFrames se concatenan en modo
        `diagonal_relaxed` y se guardan en `self.parquet_path`.

        Returns:
            dict: Diccionario con los campos:
                - `files_processed` (int): Número de CSVs procesados correctamente.
                - `records_total` (int): Total de registros consolidados.
                - `errors` (int): Número de CSVs que produjeron error.
        """
        stats = {"files_processed": 0, "records_total": 0, "errors": 0}
        dataframes = []

        # Regex para extraer metadatos del nombre de archivo
        pattern = re.compile(
            r"pleno-(\d{4}-\d{2}-\d{2})--(Número \d+)\.\s*(.+ Legislatura)"
        )

        if not os.path.exists(self.csv_folder):
            self.logger.error(f"Carpeta no encontrada: {self.csv_folder}")
            return stats

        # Procesar cada CSV
        for csv_file in os.listdir(self.csv_folder):
            if not csv_file.endswith('.csv'):
                continue

            csv_path = os.path.join(self.csv_folder, csv_file)

            try:
                df = pl.read_csv(csv_path)

                # Renombrar columnas si es necesario
                if list(df.columns[:3]) == ['Unnamed: 0', 'archivo', 'texto']:
                    df = df.rename({'archivo': 'id', 'texto': 'text'})

                # Añadir columna 'section'
                df = df.with_columns(
                    pl.lit(os.path.splitext(csv_file)[0]).alias('section')
                )

                # Normalizar unicode
                if 'id' in df.columns:
                    df = df.with_columns(
                        pl.col('id').map_elements(
                            lambda x: unicodedata.normalize("NFC", str(x)),
                            return_dtype=pl.Utf8
                        ).alias('id')
                    )

                    # Extraer metadatos con regex
                    df = df.with_columns([
                        pl.col('id').str.extract(r"pleno-(\d{4}-\d{2}-\d{2})").alias('date'),
                        pl.col('id').str.extract(r"--(Número \d+)").alias('plenary_number'),
                        pl.col('id').str.extract(r"\.\s*(.+ Legislatura)").alias('legislature')
                    ])

                dataframes.append(df)
                stats["files_processed"] += 1
                stats["records_total"] += len(df)

                self.logger.info(f"[CSV] {csv_file}: {len(df)} registros")

            except Exception as e:
                self.logger.error(f"[Error] {csv_file}: {e}")
                stats["errors"] += 1

        # Concatenar DataFrames
        if dataframes:
            final_df = pl.concat(dataframes, how="diagonal_relaxed")

            # Seleccionar columnas
            available_cols = ['id', 'text', 'section', 'date', 'plenary_number', 'legislature']
            cols_to_select = [c for c in available_cols if c in final_df.columns]
            final_df = final_df.select(cols_to_select)

            # Guardar Parquet
            final_df.write_parquet(self.parquet_path)
            self.logger.info(f"[Parquet] Guardado: {self.parquet_path}")

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de consolidación y registra el resumen final.

        Llama a `consolidate_csvs` e imprime por log las estadísticas de archivos
        procesados, registros totales y errores.
        """
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO CONSOLIDACIÓN PARLAMINT")
        self.logger.info("=" * 60)

        stats = self.consolidate_csvs()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Archivos procesados: {stats['files_processed']}")
        self.logger.info(f"  Registros totales: {stats['records_total']}")
        self.logger.info(f"  Errores: {stats['errors']}")
        self.logger.info("=" * 60)

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging con salida a fichero y consola.

        Crea un `FileHandler` que escribe en `{dataset_folder}/{basename}.log` y
        un `StreamHandler` para la consola. Ambos usan el formato:
        `%(asctime)s - %(levelname)s - %(message)s`.

        Returns:
            logging.Logger: Logger configurado listo para usar.
        """
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(self.dataset_folder, f"{os.path.basename(self.dataset_folder)}.log"),
                mode='a', encoding='utf-8'
            )
            console_handler = logging.StreamHandler()

            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        return logger


if __name__ == "__main__":
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "ParlaMint_Andalucia"],
        csv_folder="alia/patrimonio/csv"
    )
    collector.execute()

    # EDA
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    if os.path.exists(collector.parquet_path):
        df = pl.read_parquet(collector.parquet_path)
        print(f"\n📊 Total de registros: {len(df)}")
        print(f"   Columnas: {df.columns}")

        if "legislature" in df.columns:
            print(f"\n📅 DISTRIBUCIÓN POR LEGISLATURA:")
            for row in df.group_by("legislature").len().sort("legislature").head(10).iter_rows(named=True):
                print(f"   {row['legislature']}: {row['len']}")
    else:
        print("No existe archivo Parquet.")
