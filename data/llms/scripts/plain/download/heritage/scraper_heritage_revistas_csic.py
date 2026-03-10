"""Recolector de datos OAI-PMH para Revistas del CSIC.

Este módulo implementa un método que recolecta artículos de revistas
científicas del CSIC (Consejo Superior de Investigaciones Científicas)
mediante el protocolo OAI-PMH. Los metadatos se extraen de múltiples
repositorios OAI y los PDFs se descargan localmente.

Revistas incluidas:
    - Anales Cervantinos
    - Estudios Medievales
    - Archivo Español de Arqueología
    - Archivo Español de Arte
    - Arqueología de la Arquitectura
    - Estudios Gallegos
    - Hispania
    - Hispania Sacra

Example:
    Ejecución básica::

        python scraper_heritage_revistas_csic.py

    Esto conectará con los endpoints OAI de las revistas, descargará
    los metadatos y PDFs, y generará un archivo Parquet consolidado.

Attributes:
    OAI_URLS (list): Lista de URLs de endpoints OAI-PMH de las revistas.

Note:
    Los artículos están disponibles en acceso abierto a través de los
    repositorios del CSIC.
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
from requests.adapters import HTTPAdapter
from sickle import Sickle
from urllib3.util.retry import Retry


# URLs de los endpoints OAI-PMH de las revistas CSIC
OAI_URLS = [
    "https://analescervantinos.revistas.csic.es/index.php/analescervantinos/oai",
    "http://estudiosmedievales.revistas.csic.es/index.php/estudiosmedievales/oai",
    "http://aespa.revistas.csic.es/index.php/aespa/oai",
    "http://archivoespañoldearte.revistas.csic.es/index.php/aea/oai",
    "http://arqarqt.revistas.csic.es/index.php/arqarqt/oai",
    "http://estudiosgallegos.revistas.csic.es/index.php/estudiosgallegos/oai",
    "http://hispania.revistas.csic.es/index.php/hispania/oai",
    "http://hispaniasacra.revistas.csic.es/index.php/hispaniasacra/oai"
]


class DataCollector:
    """Recolector de datos OAI-PMH para revistas del CSIC.

    Esta clase gestiona la conexión con repositorios OAI-PMH, descarga
    los metadatos de artículos y los PDFs correspondientes.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs descargados.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Revistas_CSIC"]
        ... )
        >>> for url in OAI_URLS:
        ...     collector.collect_from_oai(url)
        >>> collector.save_to_parquet()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str]
    ) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset.

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
            win32net.error: Si falla la conexión al disco de red.
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

        # Configurar sesión HTTP con reintentos
        self.session = self._create_session()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] PDF folder: {self.pdf_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

    def _create_session(self) -> requests.Session:
        """Crea una sesión HTTP con política de reintentos.

        Returns:
            Sesión de requests configurada.
        """
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet.

        Args:
            parquet_path: Ruta al archivo Parquet. Si es None, usa
                self.parquet_path.

        Returns:
            Conjunto (set) con los IDs existentes.
        """
        path = parquet_path or self.parquet_path
        if os.path.exists(path):
            try:
                df = pl.read_parquet(path)
                return set(df["id"].to_list())
            except Exception:
                return set()
        return set()

    def append_record(self, record_data: dict) -> None:
        """Añade un nuevo registro al buffer en memoria.

        Args:
            record_data: Diccionario con los campos del registro.
        """
        self.records_buffer.append(record_data)

    def save_to_parquet(self) -> None:
        """Persiste los registros del buffer en el archivo Parquet.

        Si el archivo Parquet ya existe, concatena los nuevos registros
        al DataFrame existente. Después de guardar, limpia el buffer.
        """
        if not self.records_buffer:
            self.logger.info("No hay registros nuevos para guardar.")
            return

        try:
            new_df = pl.DataFrame(self.records_buffer)

            if os.path.exists(self.parquet_path):
                existing_df = pl.read_parquet(self.parquet_path)

                # Unificar tipos de columnas
                for col in existing_df.columns:
                    if col in new_df.columns:
                        existing_dtype = existing_df.schema[col]
                        new_dtype = new_df.schema[col]

                        if existing_dtype != new_dtype:
                            try:
                                existing_df = existing_df.with_columns(
                                    pl.col(col).cast(new_dtype)
                                )
                            except Exception:
                                pass

                combined_df = pl.concat([existing_df, new_df], how="diagonal_relaxed")
            else:
                combined_df = new_df

            combined_df.write_parquet(self.parquet_path)
            self.logger.info(
                f"Se guardaron {len(self.records_buffer)} registros en {self.parquet_path}"
            )
            self.records_buffer.clear()

        except Exception as e:
            self.logger.error(f"No se pudo escribir en el archivo Parquet: {e}")

    @staticmethod
    def clean_filename(name: str, replacement: str = "_") -> str:
        """Limpia un string para usarlo como nombre de archivo válido.

        Args:
            name: Nombre original (puede ser URL).
            replacement: Carácter para reemplazar caracteres inválidos.

        Returns:
            Nombre de archivo limpio y seguro (máx 150 chars).
        """
        clean_name = os.path.splitext(os.path.basename(urlparse(name).path))[0]
        clean_name = unicodedata.normalize('NFKD', clean_name).encode('ascii', 'ignore').decode('ascii')
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', replacement, clean_name)
        clean_name = re.sub(r'[\\/*?:"<>|]', replacement, clean_name)
        clean_name = re.sub(f'{replacement}+', replacement, clean_name)
        clean_name = clean_name.strip(replacement)
        clean_name = clean_name[:150]
        return clean_name if clean_name else "documento"

    def download_pdf(self, url: str, filename: str) -> str:
        """Descarga un PDF desde una URL.

        Args:
            url: URL del PDF (se convierte de view a download).
            filename: Nombre del archivo de destino.

        Returns:
            Ruta completa del archivo descargado.

        Raises:
            requests.HTTPError: Si falla la descarga.
        """
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        full_path = os.path.join(self.pdf_folder, filename)

        if os.path.exists(full_path):
            self.logger.debug(f"[PDF] {filename} ya existe. Omitiendo...")
            return full_path

        # Convertir URL de view a download
        download_url = url.replace("view", "download")

        response = self.session.get(
            download_url,
            stream=True,
            timeout=30
        )
        response.raise_for_status()

        with open(full_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        self.logger.info(f"[PDF] {filename} descargado correctamente")
        return full_path

    def collect_from_oai(self, oai_url: str) -> int:
        """Recolecta registros de un endpoint OAI-PMH.

        Conecta al repositorio OAI, itera sobre todos los registros
        y descarga los PDFs asociados.

        Args:
            oai_url: URL del endpoint OAI-PMH.

        Returns:
            Número de registros nuevos procesados.
        """
        self.logger.info(f"[OAI] Conectando a: {oai_url}")
        new_count = 0
        save_interval = 50

        try:
            sickle = Sickle(oai_url)
            records = sickle.ListRecords(metadataPrefix='oai_dc', ignore_deleted=True)

            for record in records:
                try:
                    md = record.metadata

                    # Extraer metadatos
                    titles = md.get('title', [""])
                    creators = md.get('creator', [""])
                    descriptions = md.get('description', [""])
                    publisher = md.get('publisher', [''])
                    date = md.get('date', [""])
                    types = md.get('type', [""])
                    sources = md.get('source', [""])
                    languages = md.get('language', [""])
                    identifiers = md.get('identifier', [""])
                    relations = md.get('relation', [""])

                    # Identificar URLs
                    url_article = next((i for i in identifiers if '/article/view/' in i), '')
                    url_pdf = next((r for r in relations if '/article/view/' in r), '')
                    doi = next((i for i in identifiers if i.startswith('10.')), '')

                    # Generar ID
                    item_id = f"{sources[0]}.pdf" if sources[0] else ""

                    if not item_id or item_id in self.existing_ids or not url_pdf:
                        continue

                    # Descargar PDF
                    try:
                        pdf_path = self.download_pdf(url_pdf, item_id)
                    except Exception as e:
                        self.logger.error(f"[PDF] Error descargando {item_id}: {e}")
                        continue

                    # Parsear campos del source
                    article_fields = [field.strip() for field in sources[0].split(';')]

                    def get_field(fields, index, default=""):
                        return fields[index] if len(fields) > index and fields[index] else default

                    # Añadir registro
                    self.append_record({
                        "id": item_id,
                        "url_pdf": url_pdf,
                        "url_article": url_article,
                        "title": titles[-1] if titles else "",
                        "journal": get_field(article_fields, 0),
                        "volume": get_field(article_fields, 1),
                        "pages": get_field(article_fields, 2),
                        "authors": creators,
                        "description": descriptions[-1] if descriptions else "",
                        "publisher": publisher,
                        "date": date[-1] if date else "",
                        "type": types,
                        "source": sources,
                        "language": languages,
                        "doi": doi,
                        "pdf_path": pdf_path,
                        "text": ""  # Se rellenará en postproceso con OCR
                    })

                    self.existing_ids.add(item_id)
                    new_count += 1

                    # Guardar incrementalmente
                    if len(self.records_buffer) >= save_interval:
                        self.save_to_parquet()

                except Exception as e:
                    self.logger.error(f"[OAI] Error procesando registro: {e}")

        except Exception as e:
            self.logger.error(f"[OAI] Error conectando a {oai_url}: {e}")

        self.logger.info(f"[OAI] {oai_url}: {new_count} registros nuevos")
        return new_count

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Itera sobre todos los endpoints OAI configurados y descarga
        los artículos y PDFs.
        """
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE REVISTAS CSIC")
        self.logger.info("=" * 60)

        total_new = 0

        for oai_url in OAI_URLS:
            count = self.collect_from_oai(oai_url)
            total_new += count

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Endpoints OAI procesados: {len(OAI_URLS)}")
        self.logger.info(f"  Artículos nuevos: {total_new}")
        self.logger.info("=" * 60)

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(
                    self.dataset_folder,
                    f"{os.path.basename(self.dataset_folder)}.log"
                ),
                mode='a',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        return logger


if __name__ == "__main__":
    # Crear instancia del recolector de datos
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Revistas_CSIC"]
    )

    # Ejecutar proceso de recolección
    collector.execute()

    # =========================================================================
    # ANÁLISIS EXPLORATORIO DEL DATASET
    # =========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    if os.path.exists(collector.parquet_path):
        df = pl.read_parquet(collector.parquet_path)

        print(f"\n📊 ESTADÍSTICAS GENERALES:")
        print(f"   Total de registros: {len(df)}")
        print(f"   Columnas: {df.columns}")

        # Distribución por revista
        print(f"\n📚 DISTRIBUCIÓN POR REVISTA:")
        print("-" * 60)
        journal_counts = df.group_by("journal").count().sort("count", descending=True)
        for row in journal_counts.iter_rows(named=True):
            print(f"   {row['journal'][:40]:40s}: {row['count']:6d}")

        # Análisis de valores nulos
        print(f"\n📋 ANÁLISIS DE VALORES NULOS:")
        print("-" * 60)
        for col in df.columns:
            null_count = df.filter(pl.col(col).is_null()).height
            pct = (null_count / len(df)) * 100 if len(df) > 0 else 0
            print(f"   {col:15s}: {null_count:6d} nulos ({pct:5.1f}%)")

        # Análisis de duplicados
        print(f"\n🔄 ANÁLISIS DE DUPLICADOS:")
        print("-" * 60)
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
