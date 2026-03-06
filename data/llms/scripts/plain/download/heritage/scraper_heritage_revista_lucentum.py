"""Recolector de datos para Revista Lucentum (Universidad de Alicante).

Este módulo implementa un método que recolecta artículos de la revista
Lucentum usando el protocolo OAI-PMH. Los PDFs se descargan y los
metadatos se almacenan en Parquet.

La revista Lucentum es:
    - Revista de Prehistoria, Arqueología e Historia Antigua
    - Publicada por la Universidad de Alicante
    - Acceso abierto con licencias Creative Commons

Example:
    Ejecución básica::

        python scraper_heritage_revista_lucentum.py

    Esto consultará el endpoint OAI-PMH, descargará PDFs
    y generará un archivo Parquet con metadatos.

Attributes:
    OAI_URL (str): URL del endpoint OAI-PMH de la revista.

Note:
    Los datos son de acceso abierto.
    URL: https://lucentum.ua.es
"""

import asyncio
import logging
import os
import re
import unicodedata
from urllib.parse import urlparse

import aiofiles
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from sickle import Sickle


# URL del endpoint OAI-PMH
OAI_URL = "https://lucentum.ua.es/oai"

# Licencias permisivas que permiten uso comercial
ALLOWED_LICENSES = [
    "https://creativecommons.org/licenses/by/4.0",
    "https://creativecommons.org/licenses/by/3.0",
    "https://creativecommons.org/licenses/by-sa/4.0",
    "https://creativecommons.org/publicdomain/zero/1.0",
    "http://creativecommons.org/licenses/by/4.0",
    "http://creativecommons.org/licenses/by-sa/4.0",
    "cc-by", "cc-by-sa", "cc0", "public domain"
]


class DataCollector:
    """Recolector de datos OAI-PMH para Revista Lucentum.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el repositorio OAI-PMH de Lucentum, descargando PDFs
    y almacenando metadatos.

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
        ...     folders=["ALIA", "Revista_Lucentum"]
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

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] PDF folder: {self.pdf_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

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
        """Limpia un string para usarlo como nombre de archivo.

        Args:
            name: Nombre original (puede ser texto o URL).
            replacement: Caracter de reemplazo para caracteres inválidos.

        Returns:
            Nombre de archivo válido.
        """
        parsed = urlparse(name)
        clean = os.path.splitext(os.path.basename(parsed.path))[0] if parsed.scheme else name

        # Normalizar acentos
        clean = clean.replace("–", "-").replace("—", "-")
        clean = unicodedata.normalize('NFKD', clean).encode('ascii', 'ignore').decode('ascii')
        clean = re.sub(r'[^a-zA-Z0-9_-]+', replacement, clean)
        clean = re.sub(f'{replacement}+', replacement, clean)
        clean = clean.strip(replacement)[:150]

        return clean if clean else "documento"

    @staticmethod
    def is_permissive_license(license_text: str) -> bool:
        """Verifica si una licencia permite uso comercial.

        Args:
            license_text: Texto de la licencia.

        Returns:
            True si la licencia es permisiva.
        """
        text = (license_text or "").strip().lower()
        if not text:
            return False

        for allowed in ALLOWED_LICENSES:
            if allowed in text:
                return True

        if "creativecommons.org" in text and "by" in text:
            if not any(tag in text for tag in ("nc", "nd")):
                return True

        return False

    async def download_pdf(self, filename: str, url: str) -> str:
        """Descarga un PDF usando Playwright.

        Args:
            filename: Nombre del archivo (sin extensión).
            url: URL del PDF.

        Returns:
            Ruta del archivo descargado.

        Raises:
            ValueError: Si no se pudo descargar el PDF.
        """
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        path = os.path.join(self.pdf_folder, filename)

        if os.path.exists(path):
            self.logger.debug(f"[PDF] {filename} ya existe. Omitiendo...")
            return path

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0",
                ignore_https_errors=True,
                accept_downloads=True
            )
            page = await context.new_page()

            try:
                # Intento directo
                response = await page.request.get(url, timeout=30000)

                if response.status == 429:
                    raise Exception("Too Many Requests (429)")

                content_type = (response.headers.get("content-type") or "").lower()
                content = await response.body()

                if "pdf" in content_type or content.startswith(b"%PDF"):
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)
                    self.logger.info(f"[PDF] {filename} descargado")
                    return path

                # Fallback: navegación con expect_download
                async with page.expect_download(timeout=30000) as download_info:
                    await page.goto(url, timeout=30000)

                download = await download_info.value
                await download.save_as(path)
                self.logger.info(f"[PDF] {filename} descargado (navegación)")
                return path

            except PlaywrightTimeout:
                self.logger.warning(f"[Timeout] {url}")
                raise ValueError(f"Timeout descargando {url}")
            except Exception as e:
                self.logger.error(f"[Error] Descargando {url}: {e}")
                raise
            finally:
                await browser.close()

    async def collect_from_oai(self) -> dict:
        """Recopila registros desde el endpoint OAI-PMH.

        Returns:
            Diccionario con estadísticas de la recolección.
        """
        stats = {
            "records_total": 0,
            "records_new": 0,
            "downloads_success": 0,
            "errors": 0
        }
        save_interval = 20

        try:
            sickle = Sickle(OAI_URL)
            records = sickle.ListRecords(metadataPrefix='oai_dc', ignore_deleted=True)

            for record in records:
                stats["records_total"] += 1
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
                rights = md.get('rights', [""])

                # Identificar URLs
                url_article = next((i for i in identifiers if '/article/view/' in i), '')
                url_pdf = next((r for r in relations if '/article/view/' in r), '')
                doi = next((i for i in identifiers if i.startswith('10.')), '')

                record_id = f"{self.clean_filename(sources[0])}.pdf" if sources[0] else ""

                if not record_id or record_id in self.existing_ids or not url_pdf:
                    continue

                try:
                    pdf_path = await self.download_pdf(record_id, url_pdf)
                    stats["downloads_success"] += 1

                    # Parsear source
                    article_fields = [f.strip() for f in sources[0].split(';')]

                    def get_field(fields, idx, default=""):
                        return fields[idx] if len(fields) > idx else default

                    self.append_record({
                        "id": record_id,
                        "url_pdf": url_pdf,
                        "url_article": url_article,
                        "title": titles[-1] if titles else "",
                        "journal": get_field(article_fields, 0),
                        "volume": get_field(article_fields, 1),
                        "pages": get_field(article_fields, 2),
                        "authors": ", ".join(creators) if isinstance(creators, list) else creators,
                        "description": descriptions[0] if descriptions else "",
                        "publisher": publisher[0] if publisher else "",
                        "date": date[-1] if date else "",
                        "type": types[0] if types else "",
                        "language": languages[0] if languages else "",
                        "doi": doi,
                        "rights": rights[-1] if rights else "",
                        "pdf_path": pdf_path
                    })

                    self.existing_ids.add(record_id)
                    stats["records_new"] += 1

                    if len(self.records_buffer) >= save_interval:
                        self.save_to_parquet()

                except Exception as e:
                    self.logger.error(f"[Error] Procesando {record_id}: {e}")
                    stats["errors"] += 1

        except Exception as e:
            self.logger.error(f"[OAI-PMH] Error: {e}")
            stats["errors"] += 1

        return stats

    def postprocess(self) -> None:
        """Filtra registros por licencia permisiva y limpia duplicados."""
        if not os.path.exists(self.parquet_path):
            self.logger.warning("[Postprocess] No hay archivo Parquet")
            return

        try:
            df = pl.read_parquet(self.parquet_path)
            initial = len(df)

            # Eliminar nulos y duplicados
            df = df.unique(subset=["id"], keep="first")
            df = df.fill_null("")

            # Filtrar por idioma español
            df = df.filter(pl.col("language").str.contains("spa"))

            # Filtrar licencias permisivas
            df = df.filter(
                pl.col("rights").map_elements(
                    self.is_permissive_license,
                    return_dtype=pl.Boolean
                )
            )

            df.write_parquet(self.parquet_path)
            self.logger.info(
                f"[Postprocess] {initial} -> {len(df)} registros tras filtrado"
            )

        except Exception as e:
            self.logger.error(f"[Postprocess] Error: {e}")

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE REVISTA LUCENTUM")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_from_oai())

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Postprocesado
        self.postprocess()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Registros OAI totales: {stats['records_total']}")
        self.logger.info(f"  Registros nuevos: {stats['records_new']}")
        self.logger.info(f"  Descargas exitosas: {stats['downloads_success']}")
        self.logger.info(f"  Errores: {stats['errors']}")
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
    # Crear instancia del recolector
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Revista_Lucentum"]
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

        # Análisis de valores nulos
        print(f"\n📋 ANÁLISIS DE VALORES NULOS:")
        print("-" * 60)
        for col in df.columns:
            null_count = df.filter(pl.col(col).is_null()).height
            pct = (null_count / len(df)) * 100 if len(df) > 0 else 0
            print(f"   {col:15s}: {null_count:6d} nulos ({pct:5.1f}%)")

        # Análisis de duplicados
        print(f"\n🔄 ANÁLISIS DE DUPLICADOS:")
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        # Distribución por año
        print(f"\n📅 DISTRIBUCIÓN POR AÑO:")
        if "date" in df.columns:
            date_counts = df.group_by("date").len().sort("date", descending=True).head(10)
            for row in date_counts.iter_rows(named=True):
                print(f"   {row['date']}: {row['len']} artículos")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
