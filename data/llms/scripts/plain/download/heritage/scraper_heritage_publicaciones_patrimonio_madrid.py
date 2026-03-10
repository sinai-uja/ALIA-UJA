"""Recolector de datos para Publicaciones de Patrimonio Cultural de Madrid.

Este módulo implementa un método que recolecta publicaciones de la
Consejería de Cultura, Turismo y Deporte de la Comunidad de Madrid.
Los PDFs se descargan y almacenan en Parquet.

El portal contiene:
    - Publicaciones sobre patrimonio cultural
    - Documentos de la Consejería de Cultura

Example:
    Ejecución básica::

        python scraper_heritage_publicaciones_patrimonio_madrid.py

    Esto navegará por las publicaciones, descargará PDFs
    y generará un archivo Parquet con metadatos.

Attributes:
    NAV_URL (str): URL de navegación para filtrar publicaciones.
    MAIN_URL (str): URL principal del portal.

Note:
    Los datos son de acceso público.
    URL: https://www.comunidad.madrid/publicamadrid
"""

import asyncio
import logging
import os
import re
import unicodedata
from urllib.parse import urlparse

import polars as pl
import requests
import win32net
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# URLs del portal
MAIN_URL = "https://www.comunidad.madrid"
NAV_URL = (
    "https://www.comunidad.madrid/publicamadrid"
    "?f[0]=consejeria%3A%22Consejer%C3%ADa%20de%20Cultura"
    "%2C%20Turismo%20y%20Deporte%22&f[1]=is_version_digital%3A%221%22&page={page}"
)


class DataCollector:
    """Recolector de datos para Publicaciones de Patrimonio Madrid.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el portal PublicaMadrid.

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
        ...     folders=["ALIA", "Publicaciones_Patrimonio_Madrid"]
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

    def download_pdf(self, url: str) -> str:
        """Descarga un PDF desde una URL."""
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            filename = f"{self.clean_filename(url)}.pdf"
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

    async def process_publication(self, url: str) -> dict:
        """Procesa una publicación individual.

        Args:
            url: URL de la publicación.

        Returns:
            Diccionario con los datos extraídos.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000)

                record = {"url_web": url}

                try:
                    pdf_link = await page.locator("#dsurl a").first.get_attribute("href")
                    record["url_pdf"] = pdf_link
                except Exception:
                    record["url_pdf"] = ""

                try:
                    record["ref"] = (await page.locator("#referencia").inner_text()).strip().removeprefix("Ref. ").strip()
                except Exception:
                    record["ref"] = ""

                try:
                    record["title"] = (await page.locator("#titulo").inner_text()).strip()
                except Exception:
                    record["title"] = ""

                try:
                    record["collection"] = (await page.locator("#coleccion").inner_text()).strip().removeprefix("Colección: ").strip()
                except Exception:
                    record["collection"] = ""

                try:
                    record["publisher"] = (await page.locator("#uor_org").inner_text()).strip()
                except Exception:
                    record["publisher"] = ""

                try:
                    record["info_resource"] = (await page.locator("#datos").inner_text()).strip()
                except Exception:
                    record["info_resource"] = ""

                try:
                    record["summary"] = (await page.locator("#extracto p").inner_text()).strip()
                except Exception:
                    record["summary"] = ""

                return record

            except PlaywrightTimeout:
                self.logger.warning(f"[Timeout] {url}")
                return {}
            except Exception as e:
                self.logger.error(f"[Error] {url}: {e}")
                return {}
            finally:
                await browser.close()

    async def navigate_list_page(self, page_num: int) -> list:
        """Navega por una página de listado y obtiene URLs."""
        url = NAV_URL.format(page=page_num)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000)
                self.logger.info(f"[Página] {page_num}")

                cards = await page.query_selector_all("div.views-field.views-field-ss-titulo a")
                urls = []

                for card in cards:
                    href = await card.get_attribute("href")
                    if href:
                        urls.append(MAIN_URL + href)

                return urls

            except Exception as e:
                self.logger.error(f"[Error] Página {page_num}: {e}")
                return []
            finally:
                await browser.close()

    async def collect_publications(self, max_pages: int = 107) -> dict:
        """Recopila publicaciones de todas las páginas.

        Args:
            max_pages: Número máximo de páginas a procesar.

        Returns:
            Diccionario con estadísticas.
        """
        stats = {
            "pages_processed": 0,
            "publications_new": 0,
            "errors": 0
        }
        save_interval = 10

        for page_num in range(1, max_pages + 1):
            try:
                urls = await self.navigate_list_page(page_num)
                stats["pages_processed"] += 1

                for url in urls:
                    record = await self.process_publication(url)

                    if not record or not record.get("url_pdf"):
                        stats["errors"] += 1
                        continue

                    # Descargar PDF
                    pdf_id = self.download_pdf(record["url_pdf"])

                    if not pdf_id:
                        stats["errors"] += 1
                        continue

                    if pdf_id in self.existing_ids:
                        continue

                    self.append_record({
                        "id": pdf_id,
                        **record
                    })
                    self.existing_ids.add(pdf_id)
                    stats["publications_new"] += 1

                    if len(self.records_buffer) >= save_interval:
                        self.save_to_parquet()

            except Exception as e:
                self.logger.error(f"[Error] Página {page_num}: {e}")
                stats["errors"] += 1

        return stats

    def execute(self, max_pages: int = 107) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN PUBLICACIONES PATRIMONIO MADRID")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_publications(max_pages))

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Páginas procesadas: {stats['pages_processed']}")
        self.logger.info(f"  Publicaciones nuevas: {stats['publications_new']}")
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
        folders=["ALIA", "Publicaciones_Patrimonio_Madrid"]
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

        if "collection" in df.columns:
            print(f"\n📚 DISTRIBUCIÓN POR COLECCIÓN:")
            for row in df.group_by("collection").len().sort("len", descending=True).head(10).iter_rows(named=True):
                print(f"   {row['collection'][:40]:42s}: {row['len']:4d}")
    else:
        print("No existe archivo Parquet.")
