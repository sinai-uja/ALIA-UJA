"""Recolector de datos para PCI de Comunidades Autónomas.

Este módulo implementa un método que recolecta información sobre
el Patrimonio Cultural Inmaterial (PCI) de las Comunidades Autónomas
de España. Los datos se extraen navegando por el portal del
Ministerio de Cultura.

El portal contiene:
    - Registros de PCI por Comunidad Autónoma
    - Descripciones, imágenes y ubicaciones geográficas
    - Patrimonio cultural inmaterial declarado

Example:
    Ejecución básica::

        python scraper_heritage_pci_ccaa.py

    Esto navegará por las CCAA, extraerá información
    y generará un archivo Parquet con metadatos.

Attributes:
    PORTAL_URL (str): URL principal del portal PCI CCAA.

Note:
    Los datos son de acceso público.
    URL: https://www.portalinmaterial.cultura.gob.es/pci-ccaa.html
"""

import asyncio
import logging
import os
from urllib.parse import urljoin

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


# URL del portal PCI CCAA
PORTAL_URL = "https://www.portalinmaterial.cultura.gob.es/pci-ccaa.html"


class DataCollector:
    """Recolector de datos para PCI de Comunidades Autónomas.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el Portal del Patrimonio Inmaterial, extrayendo información
    de elementos PCI por CCAA y provincia.

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
        ...     folders=["ALIA", "PCI_CCAA"]
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

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
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
        """Obtiene los IDs de registros ya existentes en el Parquet.

        Args:
            parquet_path: Ruta al archivo Parquet.

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
        """Persiste los registros del buffer en el archivo Parquet."""
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

    async def extract_item_info(
        self,
        item_url: str,
        page: Page,
        province: str,
        region: str
    ) -> dict:
        """Extrae información de un elemento PCI.

        Args:
            item_url: URL de la página del elemento.
            page: Objeto Page de Playwright.
            province: Provincia asociada.
            region: Comunidad Autónoma asociada.

        Returns:
            Diccionario con los datos extraídos.
        """
        try:
            await page.goto(item_url, timeout=30000)

            # Título
            title_el = await page.query_selector("h1")
            title = (await title_el.inner_text()).strip() if title_el else ""

            if title in self.existing_ids:
                return {}

            # Texto
            paragraphs = await page.query_selector_all("p.ta-justify")
            text = "\n".join([
                (await p.inner_text()).strip() for p in paragraphs
            ])

            return {
                "id": title,
                "url": item_url,
                "region": region,
                "province": province or "",
                "text": text
            }

        except PlaywrightTimeout:
            self.logger.warning(f"[Timeout] {item_url}")
            return {}
        except Exception as e:
            self.logger.error(f"[Error] {item_url}: {e}")
            return {}

    async def collect_pci_data(self) -> dict:
        """Recopila elementos PCI de todas las CCAA.

        Returns:
            Diccionario con estadísticas de la recolección.
        """
        stats = {
            "ccaa_processed": 0,
            "items_new": 0,
            "errors": 0
        }
        save_interval = 10

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.url, timeout=60000)

                # Obtener lista de CCAA
                link_els = await page.query_selector_all("ul.lista li a")
                ccaa_data = []
                for el in link_els:
                    href = await el.get_attribute("href")
                    name = await el.inner_text()
                    if href:
                        ccaa_data.append((name.strip(), urljoin(self.url, href)))

                self.logger.info(f"[CCAA] {len(ccaa_data)} comunidades encontradas")

                for region_name, region_url in ccaa_data:
                    try:
                        self.logger.info(f"[CCAA] Procesando {region_name}")
                        await page.goto(region_url, timeout=30000)

                        # Items sin provincia (directamente en CCAA)
                        all_items = await page.query_selector_all("div.cim.pq.formato-h.enlace a")
                        all_urls = set()
                        for item in all_items:
                            href = await item.get_attribute("href")
                            if href:
                                all_urls.add(urljoin(self.url, href))

                        # Items por provincia
                        province_els = await page.query_selector_all("div.elemento")
                        province_items = []

                        for province_el in province_els:
                            province_name_el = await province_el.query_selector("p")
                            province_name = (await province_name_el.inner_text()).strip() if province_name_el else ""

                            province_links = await province_el.query_selector_all("div.cim.pq.formato-h.enlace a")
                            for link in province_links:
                                href = await link.get_attribute("href")
                                if href:
                                    item_url = urljoin(self.url, href)
                                    province_items.append((province_name, item_url))
                                    all_urls.discard(item_url)

                        # Procesar items de provincias
                        for province_name, item_url in province_items:
                            data = await self.extract_item_info(item_url, page, province_name, region_name)
                            if data:
                                self.append_record(data)
                                self.existing_ids.add(data["id"])
                                stats["items_new"] += 1

                                if len(self.records_buffer) >= save_interval:
                                    self.save_to_parquet()

                        # Procesar items sin provincia
                        for item_url in all_urls:
                            data = await self.extract_item_info(item_url, page, "", region_name)
                            if data:
                                self.append_record(data)
                                self.existing_ids.add(data["id"])
                                stats["items_new"] += 1

                                if len(self.records_buffer) >= save_interval:
                                    self.save_to_parquet()

                        stats["ccaa_processed"] += 1

                    except Exception as e:
                        self.logger.error(f"[Error] {region_name}: {e}")
                        stats["errors"] += 1

            except Exception as e:
                self.logger.error(f"[Error] Principal: {e}")
                stats["errors"] += 1
            finally:
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE PCI CCAA")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_pci_data())

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  CCAA procesadas: {stats['ccaa_processed']}")
        self.logger.info(f"  Items nuevos: {stats['items_new']}")
        self.logger.info(f"  Errores: {stats['errors']}")
        self.logger.info("=" * 60)

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Returns:
            Logger configurado con nivel INFO.
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
        folders=["ALIA", "PCI_CCAA"]
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

        # Distribución por CCAA
        print(f"\n🗺️ DISTRIBUCIÓN POR CCAA:")
        print("-" * 60)
        if "region" in df.columns:
            region_counts = df.group_by("region").len().sort("len", descending=True)
            for row in region_counts.iter_rows(named=True):
                print(f"   {row['region']:30s}: {row['len']:4d} elementos")

        # Análisis de duplicados
        print(f"\n🔄 ANÁLISIS DE DUPLICADOS:")
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
