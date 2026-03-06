"""Recolector de datos para Tesis del Archivo General de Palacio.

Este módulo implementa un método que recolecta tesis doctorales
digitalizadas sobre fondos del Archivo General de Palacio.
Los PDFs se descargan y almacenan en Parquet.

El portal contiene:
    - Tesis doctorales sobre fondos documentales
    - Metadatos de publicación

Example:
    Ejecución básica::

        python scraper_heritage_tesis_palacios.py

    Esto navegará por el portal, descargará PDFs
    y generará un archivo Parquet con metadatos.

Attributes:
    MAIN_URL (str): URL principal del portal.

Note:
    Los datos son de acceso público.
    URL: https://www.patrimonionacional.es/coleccion/archivo-general-de-palacio
"""

import asyncio
import logging
import os
from urllib.parse import urljoin, urlparse

import aiofiles
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page


# URL principal del portal
MAIN_URL = (
    "https://www.patrimonionacional.es/coleccion/archivo-general-de-palacio"
    "/enlaces/archivos-y-otros-centros-de-investigacion"
    "#Tesis%20digitalizadas%20sobre%20fondos%20documentales%20del%20Archivo%20General%20de%20Palacio:"
)


class DataCollector:
    """Recolector de datos para Tesis del Archivo General de Palacio.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el portal del Patrimonio Nacional.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        url: URL principal del portal.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Tesis_Palacios"]
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str],
        url: str = None
    ) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al archivo YAML de configuración.
            folders: Lista de carpetas anidadas para crear la estructura.
            url: URL del portal. Si es None, usa MAIN_URL.
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

        # URL principal
        self.url = url or MAIN_URL

        # Logger
        self.logger = self.setup_logger()

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

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

    async def download_pdf(self, filename: str, url: str) -> str:
        """Descarga un PDF usando Playwright."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0", ignore_https_errors=True)
            page = await context.new_page()

            try:
                response = await page.request.get(url)

                if response.status == 429:
                    raise Exception("Too Many Requests (429)")

                content_type = response.headers.get("content-type", "").lower()
                content = await response.body()

                if "pdf" not in content_type and not content.startswith(b"%PDF"):
                    raise ValueError(f"No es un PDF válido: {url}")

                if not filename.lower().endswith(".pdf"):
                    filename += ".pdf"

                path = os.path.join(self.pdf_folder, filename)

                async with aiofiles.open(path, "wb") as f:
                    await f.write(content)

                self.logger.info(f"[PDF] {filename} descargado")
                return path

            except Exception as e:
                self.logger.error(f"[PDF] Error: {e}")
                return ""
            finally:
                await browser.close()

    @staticmethod
    async def safe_inner_text(page: Page, selector: str) -> str:
        """Obtiene texto de un selector de forma segura."""
        el = await page.query_selector(selector)
        return await el.inner_text() if el else ""

    @staticmethod
    async def safe_attr(page: Page, selector: str, attr: str) -> str:
        """Obtiene atributo de un selector de forma segura."""
        el = await page.query_selector(selector)
        return await el.get_attribute(attr) if el else ""

    async def extract_info(self, item_id: str, page: Page) -> dict:
        """Extrae información de una tesis.

        Args:
            item_id: Identificador del elemento.
            page: Página de Playwright.

        Returns:
            Diccionario con los datos extraídos.
        """
        data = {"id": item_id, "url_web": page.url}

        # Solo procesamos UCM
        if "ucm" not in page.url:
            return {}

        data["title"] = await self.safe_inner_text(page, "h1 span")
        data["url_pdf"] = urljoin(
            page.url,
            await self.safe_attr(page, "ds-themed-file-download-link a", "href")
        )

        # Fechas
        dates = await page.query_selector_all("div p")
        data["publication_date"] = await dates[0].inner_text() if len(dates) > 0 else ""
        data["lecture_date"] = await dates[1].inner_text() if len(dates) > 1 else ""

        # Personas
        persons = await page.query_selector_all(
            "ds-metadata-representation-list a:not(ds-author-identifiers-icons a)"
        )
        data["author"] = await persons[0].inner_text() if len(persons) > 0 else ""
        data["tutor"] = await persons[1].inner_text() if len(persons) > 1 else ""

        # Otros datos
        spans = await page.query_selector_all("ds-metadata-values span")
        data["editor"] = await spans[0].inner_text() if len(spans) > 0 else ""
        data["summary"] = await spans[1].inner_text() if len(spans) > 1 else ""
        data["topic"] = await self.safe_inner_text(page, "ds-metadata-values a")

        # Descargar PDF
        if data["url_pdf"]:
            pdf_path = await self.download_pdf(item_id, data["url_pdf"])
            data["pdf_path"] = pdf_path

        return data

    async def navigate_urls(self) -> dict:
        """Navega por las URLs y procesa tesis.

        Returns:
            Diccionario con estadísticas.
        """
        stats = {"theses_found": 0, "theses_new": 0, "errors": 0}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.url, timeout=30000)

                page_links = await page.locator('li a').all()
                valid_urls = []

                for link in page_links:
                    href = await link.get_attribute('href')
                    if href and "ucm" in href:
                        valid_urls.append(href.replace("http://", "https://", 1))

                stats["theses_found"] = len(valid_urls)
                self.logger.info(f"[Tesis] {len(valid_urls)} encontradas")

                for i, url in enumerate(valid_urls):
                    item_id = f"Tesis_Palacios_{i}"

                    if item_id in self.existing_ids:
                        continue

                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        self.logger.info(f"[Tesis] Procesando: {url[:50]}...")

                        data = await self.extract_info(item_id, page)

                        if data:
                            self.append_record(data)
                            self.existing_ids.add(item_id)
                            stats["theses_new"] += 1

                    except Exception as e:
                        self.logger.error(f"[Error] {url}: {e}")
                        stats["errors"] += 1
                        await asyncio.sleep(2)

            except Exception as e:
                self.logger.error(f"[Error] Principal: {e}")
                stats["errors"] += 1
            finally:
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN TESIS PALACIOS")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.navigate_urls())

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Tesis encontradas: {stats['theses_found']}")
        self.logger.info(f"  Tesis nuevas: {stats['theses_new']}")
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
        folders=["ALIA", "Tesis_Palacios"]
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
    else:
        print("No existe archivo Parquet.")
