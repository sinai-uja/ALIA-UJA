"""Recolector de datos para Obras Singulares de los Museos de Andalucía.

Este módulo implementa un método que recolecta información sobre
obras singulares de los museos de Andalucía. Los datos se extraen
navegando por las páginas de cada museo y descargando imágenes.

Los museos incluidos son:
    - Museo de Almería, Cádiz, Huelva, Jaén, Málaga
    - Museos Arqueológicos/Etnológicos de Córdoba, Granada, Úbeda
    - Museos de Bellas Artes de Córdoba, Granada, Sevilla
    - Museos de Artes y Costumbres Populares

Example:
    Ejecución básica::

        python scraper_heritage_obras_singulares_museos_andalucia.py

    Esto navegará por los museos, extraerá información de obras
    y generará un archivo Parquet con metadatos e imágenes.

Attributes:
    MUSEUM_URLS (dict): Diccionario con URLs de cada museo.

Note:
    Los datos son de acceso público a través del portal
    de Museos de Andalucía.
    URL: https://www.museosdeandalucia.es
"""

import asyncio
import logging
import os

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


# URLs de los museos
MUSEUM_URLS = {
    "Museo de Almería": "https://www.museosdeandalucia.es/web/museodealmeria/obras-singulares",
    "Museo de Cádiz": "https://www.museosdeandalucia.es/web/museodecadiz/obras-singulares",
    "Museo Arqueológico y Etnológico de Córdoba": "https://www.museosdeandalucia.es/w/museoarqueologicodecordoba/obras-singulares",
    "Museo de Bellas Artes de Córdoba": "https://www.museosdeandalucia.es/w/museodebellasartesdecordoba/obras-singulares",
    "Museo Arqueológico y Etnológico de Granada": "https://www.museosdeandalucia.es/w/museoarqueologicodegranada/obras-singulares",
    "Museo de Bellas Artes de Granada": "https://www.museosdeandalucia.es/w/museodebellasartesdegranada/obras-singulares",
    "Museo Casa de los Tiros de Granada": "https://www.museosdeandalucia.es/w/museocasadelostirosdegranada/obras-singulares",
    "Museo de Huelva": "https://www.museosdeandalucia.es/w/museodehuelva/obras-singulares",
    "Museo Arqueológico de Úbeda": "https://www.museosdeandalucia.es/w/museoarqueologicodeubeda/obras-singulares",
    "Museo de Artes y Costumbres Populares del Alto Guadalquivir": "https://www.museosdeandalucia.es/w/museodeartesycostumbrespopularesdelaltoguadalquivir/obras-singulares",
    "Museo de Jaén": "https://www.museosdeandalucia.es/w/museodejaen/obras-singulares",
    "Museo de Málaga": "https://www.museosdeandalucia.es/w/museodemalaga/obras-singulares",
    "Museo Arqueológico de Sevilla": "https://www.museosdeandalucia.es/w/museoarqueologicodesevilla/obras-singulares",
    "Museo de Artes y Costumbres Populares de Sevilla": "https://www.museosdeandalucia.es/w/museodeartesycostumbrespopularesdesevilla/obras-singulares",
    "Museo de Bellas Artes de Sevilla": "https://www.museosdeandalucia.es/w/museodebellasartesdesevilla/obras-singulares"
}


class DataCollector:
    """Recolector de datos para Obras Singulares de Museos de Andalucía.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el portal de Museos de Andalucía, extrayendo información
    de obras singulares y descargando imágenes.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        urls: Diccionario de URLs de museos.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Obras_Singulares_Museos_Andalucia"]
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str],
        urls: dict = None
    ) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al archivo YAML de configuración.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset.
            urls: Diccionario de URLs de museos. Si es None, usa MUSEUM_URLS.

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

        # URLs de museos
        self.urls = urls or MUSEUM_URLS

        # Logger
        self.logger = self.setup_logger()

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")
        self.logger.info(f"[Init] Museos a procesar: {len(self.urls)}")

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

    async def extract_artwork_info(self, link: str, section: str) -> dict:
        """Extrae información detallada de una obra singular.

        Args:
            link: URL de la página de la obra.
            section: Nombre del museo.

        Returns:
            Diccionario con los datos extraídos.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(link, timeout=30000)

                # Título
                title_el = await page.query_selector("h3.header-title span")
                title = (await title_el.inner_text()).strip() if title_el else ""

                # Descripción
                desc_el = await page.query_selector("div.detalle > div.body-content")
                description = (await desc_el.inner_text()).strip() if desc_el else ""

                # Procedencia
                origin = ""
                origin_sel = await page.query_selector("h4:has-text('Procedencia')")
                if origin_sel:
                    origin_el = await origin_sel.evaluate_handle("node => node.nextElementSibling")
                    if origin_el:
                        origin = (await origin_el.inner_text()).strip()

                # Comentario
                comment = ""
                comment_sel = await page.query_selector("h4:has-text('Comentario')")
                if comment_sel:
                    comment_el = await comment_sel.evaluate_handle("node => node.nextElementSibling")
                    if comment_el:
                        comment = (await comment_el.inner_text()).strip()

                # Item ID
                item_id = f"{section}_{link.split('?')[0].split('/')[-1]}"

                return {
                    "id": item_id,
                    "url": link,
                    "section": section,
                    "title": title,
                    "description": description,
                    "origin": origin,
                    "comment": comment,
                    "text": f"{title}\n{description}\n{origin}\n{comment}"
                }

            except PlaywrightTimeout:
                self.logger.warning(f"[Timeout] {link}")
                return {}
            except Exception as e:
                self.logger.error(f"[Error] {link}: {e}")
                return {}
            finally:
                await browser.close()

    async def navigate_to_next_page(self, page: Page) -> bool:
        """Navega a la siguiente página de resultados.

        Args:
            page: Objeto Page de Playwright.

        Returns:
            True si hay siguiente página, False si no.
        """
        next_li = await page.query_selector("li:has-text('Siguiente')")

        if not next_li:
            return False

        li_class = await next_li.get_attribute("class") or ""
        if "disabled" in li_class:
            return False

        next_a = await next_li.query_selector("a")
        if next_a:
            await next_a.click()
            await page.wait_for_load_state("networkidle")
            return True

        return False

    async def process_museum(self, url: str, section: str) -> int:
        """Procesa las obras singulares de un museo.

        Args:
            url: URL de la página de obras singulares.
            section: Nombre del museo.

        Returns:
            Número de obras procesadas.
        """
        count = 0
        save_interval = 10

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000)
                self.logger.info(f"[Museo] Procesando: {section}")

                while True:
                    # Obtener URLs de obras
                    items = await page.query_selector_all("p.descripcion a")
                    item_urls = [await item.get_attribute("href") for item in items]

                    for link in item_urls:
                        if not link:
                            continue

                        # Verificar si ya existe
                        item_id = f"{section}_{link.split('?')[0].split('/')[-1]}"
                        if item_id in self.existing_ids:
                            continue

                        self.logger.info(f"[Obra] {link}")
                        data = await self.extract_artwork_info(link, section)

                        if data:
                            self.append_record(data)
                            self.existing_ids.add(item_id)
                            count += 1

                            if len(self.records_buffer) >= save_interval:
                                self.save_to_parquet()

                    # Siguiente página
                    if not await self.navigate_to_next_page(page):
                        break

                    self.logger.info("[Paginación] Siguiente página...")

            except Exception as e:
                self.logger.error(f"[Museo] Error en {section}: {e}")
            finally:
                await browser.close()

        return count

    async def collect_artworks(self) -> dict:
        """Recopila obras de todos los museos.

        Returns:
            Diccionario con estadísticas de la recolección.
        """
        stats = {
            "museums_processed": 0,
            "artworks_new": 0,
            "errors": 0
        }

        for section, url in self.urls.items():
            try:
                count = await self.process_museum(url, section)
                stats["artworks_new"] += count
                stats["museums_processed"] += 1
            except Exception as e:
                self.logger.error(f"[Error] {section}: {e}")
                stats["errors"] += 1

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE OBRAS SINGULARES")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_artworks())

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Museos procesados: {stats['museums_processed']}")
        self.logger.info(f"  Obras nuevas: {stats['artworks_new']}")
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
        folders=["ALIA", "Obras_Singulares_Museos_Andalucia"]
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

        # Distribución por museo
        print(f"\n🏛️ DISTRIBUCIÓN POR MUSEO:")
        print("-" * 60)
        if "section" in df.columns:
            museum_counts = df.group_by("section").len().sort("len", descending=True)
            for row in museum_counts.iter_rows(named=True):
                print(f"   {row['section'][:40]:42s}: {row['len']:4d} obras")

        # Análisis de duplicados
        print(f"\n🔄 ANÁLISIS DE DUPLICADOS:")
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
