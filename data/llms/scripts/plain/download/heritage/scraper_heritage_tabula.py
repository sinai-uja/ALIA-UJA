"""Recolector de datos para TABULA de Andalucía.

Este módulo implementa un método que recolecta documentos del
repositorio TABULA de la Junta de Andalucía.
Los PDFs se descargan y almacenan en Parquet.

El portal contiene:
    - Documentos históricos digitalizados
    - Memorias de intervenciones arqueológicas
    - Informes técnicos de patrimonio

Example:
    Ejecución básica::

        python scraper_heritage_tabula.py

    Esto navegará por el repositorio, descargará PDFs
    y generará un archivo Parquet con metadatos.

Attributes:
    NAV_URL (str): URL de navegación del repositorio.
    MAIN_URL (str): URL principal del portal.

Note:
    Los datos son de acceso público.
    URL: https://www.juntadeandalucia.es/cultura/tabula
"""

import asyncio
import logging
import os
import re
import unicodedata
from urllib.parse import urlparse

import aiohttp
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page


# URLs del portal
NAV_URL = "https://www.juntadeandalucia.es/cultura/tabula/simple-search?query=&sort_by=score&order=desc&rpp=100&etal=0&start={batch}"


class DataCollector:
    """Recolector de datos para TABULA.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el repositorio TABULA de Andalucía.

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
        ...     folders=["ALIA", "TABULA"]
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

    async def download_pdf(self, url: str) -> str:
        """Descarga un PDF desde una URL."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=60) as response:
                    if response.status == 200:
                        filename = f"{self.clean_filename(url)}.pdf"
                        output_path = os.path.join(self.pdf_folder, filename)

                        with open(output_path, "wb") as f:
                            f.write(await response.read())

                        self.logger.info(f"[PDF] {filename} descargado")
                        return filename
        except Exception as e:
            self.logger.error(f"[PDF] Error: {e}")

        return ""

    async def parse_metadata(self, page: Page) -> dict:
        """Parsea metadatos de la tabla de información."""
        await page.wait_for_selector("table.itemDisplayTable", timeout=5000)

        rows = await page.query_selector_all("table.itemDisplayTable tr")
        data = {}

        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) != 2:
                continue

            raw_key = await cells[0].inner_text()
            key = raw_key.strip().replace("\u00a0", " ").replace(" :", "").replace(":", "").strip()

            value_cell = cells[1]
            links = await value_cell.query_selector_all("a")

            if links:
                texts = await asyncio.gather(*(link.inner_text() for link in links))
                data[key] = [text.strip() for text in texts]
            else:
                raw_html = await value_cell.inner_html()
                raw_html = raw_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
                text = re.sub(r'<[^>]+>', '', raw_html).strip()
                values = [line.strip() for line in text.splitlines() if line.strip()]
                data[key] = values if len(values) > 1 else values[0] if values else ""

        return data

    async def process_document(self, page_url: str, title: str) -> dict:
        """Procesa un documento individual.

        Args:
            page_url: URL de la página del documento.
            title: Título del documento.

        Returns:
            Diccionario con los datos extraídos o vacío.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(page_url, timeout=60000)
                self.logger.info(f"[Doc] Procesando: {title[:50]}...")

                # Buscar enlace al PDF
                await page.wait_for_selector('div[class="separacion-bitstream-enlaces"] a', timeout=5000)
                file_links = await page.locator('div[class="separacion-bitstream-enlaces"] a').all()

                if not file_links:
                    return {}

                href = await file_links[0].get_attribute('href')
                if not href or not href.endswith('.pdf'):
                    return {}

                # Descargar PDF
                pdf_id = await self.download_pdf(href)
                if not pdf_id:
                    return {}

                # Obtener metadatos
                try:
                    metadata = await self.parse_metadata(page)
                except Exception:
                    metadata = {}

                return {
                    "id": pdf_id,
                    "url": href,
                    **{k: (", ".join(v) if isinstance(v, list) else v) for k, v in metadata.items()}
                }

            except Exception as e:
                self.logger.error(f"[Doc] Error: {e}")
                return {}
            finally:
                await browser.close()

    async def navigate_list(self, url: str) -> list:
        """Navega por una página de listado y procesa documentos.

        Args:
            url: URL de la página de listado.

        Returns:
            Lista de URLs de documentos.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000)

                page_links = await page.locator('div[headers="t2"] a').all()
                items = []

                for link in page_links:
                    href = await link.get_attribute('href')
                    title = await link.text_content()
                    if href:
                        items.append((href, title))

                return items

            except Exception as e:
                self.logger.error(f"[Lista] Error: {e}")
                return []
            finally:
                await browser.close()

    async def collect_documents(self, max_items: int = 12778) -> dict:
        """Recopila documentos de todas las páginas.

        Args:
            max_items: Número máximo de items a procesar.

        Returns:
            Diccionario con estadísticas.
        """
        stats = {
            "pages_processed": 0,
            "documents_new": 0,
            "errors": 0
        }
        save_interval = 20

        for batch in range(0, max_items, 100):
            url = NAV_URL.format(batch=batch)
            page_num = batch // 100

            try:
                self.logger.info(f"[Página] {page_num}")
                items = await self.navigate_list(url)
                stats["pages_processed"] += 1

                for href, title in items:
                    pdf_id = self.clean_filename(href)

                    if pdf_id in self.existing_ids:
                        continue

                    record = await self.process_document(href, title)

                    if record:
                        self.append_record(record)
                        self.existing_ids.add(record["id"])
                        stats["documents_new"] += 1

                        if len(self.records_buffer) >= save_interval:
                            self.save_to_parquet()

            except Exception as e:
                self.logger.error(f"[Error] Página {page_num}: {e}")
                stats["errors"] += 1

        return stats

    def execute(self, max_items: int = 12778) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN TABULA")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_documents(max_items))

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Páginas procesadas: {stats['pages_processed']}")
        self.logger.info(f"  Documentos nuevos: {stats['documents_new']}")
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
        folders=["ALIA", "TABULA"]
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
