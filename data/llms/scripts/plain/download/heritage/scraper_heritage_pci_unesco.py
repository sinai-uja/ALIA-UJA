"""Recolector de datos para PCI UNESCO de España.

Este módulo implementa un método que recolecta información sobre
el Patrimonio Cultural Inmaterial (PCI) de España inscrito en
las listas de la UNESCO.

El portal contiene:
    - Manifestaciones culturales declaradas PCI UNESCO
    - Descripciones, galerías de imágenes
    - Lista Representativa, Registro de Buenas Prácticas

Example:
    Ejecución básica::

        python scraper_heritage_pci_unesco.py

    Esto navegará por el portal, extraerá información
    y generará un archivo Parquet con metadatos.

Attributes:
    PORTAL_URL (str): URL principal del portal PCI UNESCO.

Note:
    Los datos son de acceso público.
    URL: https://www.portalinmaterial.cultura.gob.es/pci-unesco.html
"""

import asyncio
import logging
import os
from urllib.parse import urljoin

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# URL del portal PCI UNESCO
PORTAL_URL = "https://www.portalinmaterial.cultura.gob.es/pci-unesco.html"


class DataCollector:
    """Recolector de datos para PCI UNESCO de España.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el Portal del Patrimonio Inmaterial UNESCO.

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
        ...     folders=["ALIA", "PCI_UNESCO"]
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

    async def collect_pci_unesco(self) -> dict:
        """Recopila elementos del PCI UNESCO."""
        stats = {"items_found": 0, "items_new": 0, "errors": 0}
        save_interval = 5

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.url, timeout=60000)

                # Obtener elementos PCI
                link_els = await page.query_selector_all(
                    "div.cle.tituloimg.gr.formato-h.dos div.enlace p.titulo a"
                )
                items_data = []

                for el in link_els:
                    href = await el.get_attribute("href")
                    title = (await el.inner_text()).strip()
                    if href:
                        items_data.append((title, urljoin(self.url, href)))

                stats["items_found"] = len(items_data)
                self.logger.info(f"[PCI] {len(items_data)} elementos encontrados")

                for i, (title, href) in enumerate(items_data):
                    item_id = f"PCI_UNESCO_{i}"

                    if item_id in self.existing_ids:
                        continue

                    try:
                        await page.goto(href, timeout=30000)

                        # Extraer texto
                        text_els = await page.query_selector_all("p.ta-justify")
                        text = "\n".join([
                            (await t.text_content()).strip() for t in text_els
                        ])

                        self.append_record({
                            "id": item_id,
                            "url": href,
                            "title": title,
                            "text": text
                        })

                        self.existing_ids.add(item_id)
                        stats["items_new"] += 1

                        if len(self.records_buffer) >= save_interval:
                            self.save_to_parquet()

                        await page.goto(self.url, timeout=30000)

                    except PlaywrightTimeout:
                        stats["errors"] += 1
                    except Exception as e:
                        self.logger.error(f"[Error] {href}: {e}")
                        stats["errors"] += 1

            except Exception as e:
                self.logger.error(f"[Error] Principal: {e}")
                stats["errors"] += 1
            finally:
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE PCI UNESCO")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_pci_unesco())

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info(f"  Elementos encontrados: {stats['items_found']}")
        self.logger.info(f"  Elementos nuevos: {stats['items_new']}")
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
        folders=["ALIA", "PCI_UNESCO"]
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
