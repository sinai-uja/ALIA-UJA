"""Recolector de datos para Yacimientos Visitables de Castilla-La Mancha.

Este módulo implementa un método que recolecta información sobre
yacimientos arqueológicos visitables en Castilla-La Mancha.
Los datos se extraen navegando por el portal.

El portal contiene:
    - Información sobre yacimientos arqueológicos
    - Descripciones, localizaciones
    - Secciones "Esenciales del Yacimiento"

Example:
    Ejecución básica::

        python scraper_heritage_yacimientos_visitables_clm.py

    Esto navegará por el portal, extraerá información
    y generará un archivo Parquet con metadatos.

Attributes:
    PORTAL_URL (str): URL principal del portal.

Note:
    Los datos son de acceso público.
    URL: https://cultura.castillalamancha.es/patrimonio/yacimientos-visitables
"""

import asyncio
import logging
import os
from urllib.parse import urljoin

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright


# URL del portal
PORTAL_URL = "https://cultura.castillalamancha.es/patrimonio/yacimientos-visitables"


class DataCollector:
    """Recolector de datos para Yacimientos Visitables CLM.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el portal de Yacimientos Visitables de Castilla-La Mancha.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        url: URL principal del portal.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Yacimientos_Visitables_CLM"]
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
            url: URL del portal. Si es None, usa PORTAL_URL.
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

        # Rutas de archivos
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # Buffer de registros
        self.records_buffer: list[dict] = []

        # URL principal
        self.url = url or PORTAL_URL

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

    async def extract_info(self, url: str, item_number: int) -> dict:
        """Extrae información de un yacimiento.

        Args:
            url: URL del yacimiento.
            item_number: Número de item para ID.

        Returns:
            Diccionario con los datos extraídos o vacío.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="load", timeout=30000)

                item_id = f"Yacimiento_Visitable_CLM_{item_number}"

                if item_id in self.existing_ids:
                    return {}

                # Título
                title_el = await page.query_selector("h1")
                title = await title_el.inner_text() if title_el else "Sin título"

                # Texto principal
                paragraphs = await page.query_selector_all("div.container div.text_with_summary.body p")
                text_parts = [await p.inner_text() for p in paragraphs if p]
                text = " ".join(text_parts).strip()

                # Secciones "Esenciales del Yacimiento"
                section_links = await page.query_selector_all("a.cbp-singlePageInline")
                self.logger.info(f"[Yacimiento] {len(section_links)} secciones en {url}")

                for idx, link in enumerate(section_links, start=1):
                    try:
                        await link.scroll_into_view_if_needed()
                        await link.click()
                        await page.wait_for_selector("div.cbp-popup-content", timeout=8000)

                        title_popup_el = await page.query_selector("div.cbp-popup-content h2")
                        title_popup = await title_popup_el.inner_text() if title_popup_el else ""

                        popup_paragraphs = await page.query_selector_all("div.cbp-popup-content div.text_with_summary.body p")
                        popup_text = " ".join([await p.inner_text() for p in popup_paragraphs if p]).strip()

                        if title_popup or popup_text:
                            text += f"\n\n{title_popup}\n{popup_text}"

                        close_btn = await page.query_selector(".cbp-popup-singlePageClose")
                        if close_btn:
                            await close_btn.click()
                            await page.wait_for_selector("div.cbp-popup-content", state="detached", timeout=5000)

                        await page.wait_for_timeout(500)

                    except Exception as e:
                        self.logger.warning(f"[Sección] Error en sección {idx}: {e}")
                        continue

                return {
                    "id": item_id,
                    "title": title,
                    "url": url,
                    "text": title + "\n" + text
                }

            except Exception as e:
                self.logger.error(f"[Yacimiento] Error: {e}")
                return {}
            finally:
                await browser.close()

    async def navigate_url(self) -> dict:
        """Navega por el portal y procesa yacimientos.

        Returns:
            Diccionario con estadísticas.
        """
        stats = {"sites_found": 0, "sites_new": 0, "errors": 0}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.url, wait_until="load", timeout=30000)

                hrefs = await page.query_selector_all('div.cbp-caption a.cbp-l-caption-buttonLeft')
                item_urls = []

                for href in hrefs:
                    attr = await href.get_attribute("href")
                    if attr:
                        item_urls.append(urljoin(os.path.dirname(self.url), attr))

                stats["sites_found"] = len(item_urls)
                self.logger.info(f"[Portal] {len(item_urls)} yacimientos encontrados")

                for i, url in enumerate(item_urls):
                    data = await self.extract_info(url, i)

                    if data:
                        self.append_record(data)
                        self.existing_ids.add(data["id"])
                        stats["sites_new"] += 1

            except Exception as e:
                self.logger.error(f"[Portal] Error: {e}")
                stats["errors"] += 1
            finally:
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN YACIMIENTOS VISITABLES CLM")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.navigate_url())

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Yacimientos encontrados: {stats['sites_found']}")
        self.logger.info(f"  Yacimientos nuevos: {stats['sites_new']}")
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
        folders=["ALIA", "Yacimientos_Visitables_CLM"]
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
