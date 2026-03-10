"""Recolector de datos para Revista PH del IAPH.

Este módulo implementa un método que recolecta artículos de la
Revista PH del Instituto Andaluz del Patrimonio Histórico (IAPH).
Los datos se extraen vía OAI-PMH y los PDFs se descargan.

La revista contiene:
    - Artículos sobre patrimonio histórico
    - Investigaciones y estudios del IAPH

Example:
    Ejecución básica::

        python scraper_heritage_revista_ph_iaph.py

    Esto extraerá registros OAI, descargará PDFs
    y generará un archivo Parquet con metadatos.

Attributes:
    OAI_URL (str): URL del endpoint OAI-PMH.

Note:
    Los datos son de acceso público.
    URL: https://www.iaph.es/revistaph
"""

import logging
import os
import re
import unicodedata
from urllib.parse import urlparse

import polars as pl
import requests
import win32net
import yaml
from sickle import Sickle


# URL OAI-PMH
OAI_URL = "https://www.iaph.es/revistaph/index.php/revistaph/oai/"


class DataCollector:
    """Recolector de datos para Revista PH del IAPH.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el endpoint OAI-PMH de la Revista PH.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Revista_PH_IAPH"]
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str]
    ) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al archivo YAML de configuración.
            folders: Lista de carpetas anidadas para crear la estructura.
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
            pass  # Ya está conectado

        # Crear estructura de carpetas
        self.dataset_folder = os.path.join(config['disk_path'], *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        # Carpeta para PDFs
        self.pdf_folder = os.path.join(self.dataset_folder, "pdf")
        os.makedirs(self.pdf_folder, exist_ok=True)

        # Rutas de archivos
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # Buffer de registros
        self.records_buffer: list[dict] = []

        # Logger
        self.logger = self.setup_logger()

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

    @staticmethod
    def clean_filename(name: str, replacement: str = "_") -> str:
        """Limpia un nombre para usarlo como nombre de archivo."""
        clean = os.path.splitext(os.path.basename(urlparse(name).path))[0]
        clean = unicodedata.normalize('NFKD', clean).encode('ascii', 'ignore').decode('ascii')
        clean = re.sub(r'[^a-zA-Z0-9_-]', replacement, clean)
        clean = re.sub(r'[\\//*?:"<>|]', replacement, clean)
        clean = re.sub(f'{replacement}+', replacement, clean)
        clean = clean.strip(replacement)[:150]
        return clean if clean else "documento"

    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet."""
        path = parquet_path or self.parquet_path
        if os.path.exists(path):
            try:
                df = pl.read_parquet(path)
                return set(df["id"].to_list())
            except Exception:
                return set()
        return set()

    def append_record(self, record_data: dict) -> None:
        """Añade un nuevo registro al buffer en memoria."""
        self.records_buffer.append(record_data)

    def save_to_parquet(self) -> None:
        """Persiste los registros del buffer en el archivo Parquet."""
        if not self.records_buffer:
            return

        try:
            new_df = pl.DataFrame(self.records_buffer)

            if os.path.exists(self.parquet_path):
                existing_df = pl.read_parquet(self.parquet_path)
                combined_df = pl.concat([existing_df, new_df], how="diagonal_relaxed")
            else:
                combined_df = new_df

            combined_df.write_parquet(self.parquet_path)
            self.logger.info(f"Guardados {len(self.records_buffer)} registros")
            self.records_buffer.clear()

        except Exception as e:
            self.logger.error(f"Error guardando Parquet: {e}")

    def download_pdf(self, url: str, title: str) -> str:
        """Descarga un PDF desde una URL."""
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            filename = f"{os.path.basename(urlparse(url).path)}_{title}.pdf"
            filename = self.clean_filename(filename) + ".pdf"
            output_path = os.path.join(self.pdf_folder, filename)

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self.logger.info(f"[PDF] {filename} descargado")
            return filename

        except Exception as e:
            self.logger.error(f"[PDF] Error: {e}")
            return ""

    def extract_records(self, url: str = None) -> dict:
        """Extrae registros OAI-PMH.

        Args:
            url: URL del endpoint OAI-PMH.

        Returns:
            Diccionario con estadísticas.
        """
        oai_url = url or OAI_URL
        stats = {"records_found": 0, "records_new": 0, "errors": 0}
        save_interval = 20

        try:
            sickle = Sickle(oai_url)
            records = sickle.ListRecords(metadataPrefix='oai_dc', ignore_deleted=True)

            for record in records:
                stats["records_found"] += 1
                md = record.metadata

                try:
                    titles = md.get('title', [""])
                    creators = md.get('creator', [""])
                    descriptions = md.get('description', [""])
                    publisher = md.get('publisher', [''])
                    date = md.get('date', [""])
                    types = md.get('type', [""])
                    formats = md.get('format', [""])
                    sources = md.get('source', [""])
                    languages = md.get('language', [""])
                    identifiers = md.get('identifier', [""])
                    relations = md.get('relation', [""])

                    # URLs relevantes
                    url_article = next((i for i in identifiers if '/article/view/' in i), '')
                    url_pdf = next((r for r in relations if '/article/view/' in r), '')
                    doi = next((i for i in identifiers if i.startswith('10.')), '')

                    if not url_pdf:
                        continue

                    title_clean = self.clean_filename(titles[-1]) if titles else "sin_titulo"

                    if title_clean in self.existing_ids:
                        continue

                    # Descargar PDF
                    pdf_id = self.download_pdf(url_pdf, title_clean)

                    if not pdf_id:
                        stats["errors"] += 1
                        continue

                    self.append_record({
                        "id": pdf_id,
                        "url_pdf": url_pdf,
                        'url_article': url_article,
                        'title': titles[-1] if titles else "",
                        'authors': "; ".join(creators) if creators else "",
                        'description': descriptions[-1] if descriptions else "",
                        'publisher': publisher[-1] if publisher else "",
                        'date': date[-1] if date else "",
                        'type': types[-1] if types else "",
                        'source': sources[-1] if sources else "",
                        'language': languages[-1] if languages else "",
                        'doi': doi
                    })

                    self.existing_ids.add(title_clean)
                    stats["records_new"] += 1

                    if len(self.records_buffer) >= save_interval:
                        self.save_to_parquet()

                except Exception as e:
                    self.logger.error(f"[Error] Registro: {e}")
                    stats["errors"] += 1

        except Exception as e:
            self.logger.error(f"[Error] OAI-PMH: {e}")
            stats["errors"] += 1

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN REVISTA PH IAPH")
        self.logger.info("=" * 60)

        stats = self.extract_records()

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Registros encontrados: {stats['records_found']}")
        self.logger.info(f"  Registros nuevos: {stats['records_new']}")
        self.logger.info(f"  Errores: {stats['errors']}")
        self.logger.info("=" * 60)

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging."""
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
        folders=["ALIA", "Revista_PH_IAPH"]
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

        if "date" in df.columns:
            print(f"\n📅 DISTRIBUCIÓN POR AÑO:")
            df_years = df.with_columns(
                pl.col("date").str.slice(0, 4).alias("year")
            )
            for row in df_years.group_by("year").len().sort("year", descending=True).head(10).iter_rows(named=True):
                print(f"   {row['year']}: {row['len']:4d}")
    else:
        print("No existe archivo Parquet.")
