"""Recolector de datos web para el catálogo de patrimonio de la Generalitat de Catalunya.

Este módulo implementa un método que recolecta información sobre elementos
del patrimonio cultural catalán desde el portal de búsqueda del Departament
de Cultura de la Generalitat de Catalunya (Patrimoni Gencat) mediante
Playwright. Los datos se extraen navigando por los resultados del catálogo
de colecciones y accediendo a cada ficha de detalle.

El catálogo de Patrimoni Gencat contiene:
    - Elementos del patrimonio cultural inmueble e inmaterial de Cataluña
    - Colecciones y bienes culturales de interés nacional y local
    - Descripciones y fichas detalladas de cada elemento patrimonial

Example:
    Ejecución básica::

        python scraper_gencat_patrimoni.py

    Esto navegará por el catálogo de patrimonio, extraerá los metadatos
    de cada ficha y los guardará en CSV y Parquet.

Note:
    Los datos son de acceso público a través del portal de Patrimoni
    del Departament de Cultura de la Generalitat de Catalunya.
    URL: https://patrimoni.gencat.cat/es/descubre/busca
"""

import asyncio
import csv
import logging
import os
import re
import shutil
import fitz  # PyMuPDF
import polars as pl
import win32net
from omegaconf import OmegaConf
from playwright.async_api import async_playwright


def sanitize_filename(filename: str) -> str:
    """Limpia una cadena para que sea un nombre válido para un archivo.

    Args:
        filename: Nombre original del archivo. Si está vacío, devuelve
            ``'sin_titulo'``.

    Returns:
        Nombre seguro para usar en rutas de archivos, o ``'sin_titulo'``
        si la entrada es vacía.
    """
    if not filename:
        return "sin_titulo"
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
    sanitized = re.sub(invalid_chars, '_', filename)
    sanitized = sanitized.strip()
    return sanitized


class GencatScraper:
    """Recolector de datos web con Playwright para el catálogo Patrimoni Gencat.

    Esta clase gestiona el proceso completo de recolección de datos desde
    el portal de búsqueda de patrimonio de la Generalitat de Catalunya,
    navegando por el catálogo de colecciones y extrayendo los metadatos
    y descripciones de cada ficha de detalle.

    Attributes:
        config: Configuración cargada desde el archivo YAML.
        dataset_folder: Ruta a la carpeta raíz del dataset.
        csv_path: Ruta al archivo CSV de salida.
        logger: Logger configurado para el recolector.
        processed_ids: Conjunto de IDs ya procesados para evitar duplicados.

    Example:
        >>> scraper = GencatScraper(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Cataluña"]
        ... )
        >>> asyncio.run(scraper.scrape())
    """

    def __init__(self, config_path: str, folders: list[str]) -> None:
        """Inicializa el recolector de datos.

        Carga la configuración, monta el disco de red, crea las carpetas
        necesarias, configura el logger y carga los IDs ya procesados.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset (ej: ['ALIA', 'Cataluña']).

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
        """
        print("[INIT] Iniciando scraper Gencat...")
        self.config = OmegaConf.load(config_path)

        # Conexión a unidad de red
        try:
            netresource = {
                'remote': self.config.disk_path,
                'password': self.config.password,
                'user': self.config.user
            }
            win32net.NetUseAdd(None, 2, netresource)
            print("[INIT] Conexión de red establecida")
        except Exception as e:
            print(f"[INIT] Nota: Intento de conexión a red: {e}")

        # Crear estructura de carpetas
        self.dataset_folder = os.path.join(self.config.disk_path, *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.logger = self.setup_logger()
        self.logger.info(f"Scraper inicializado. Dataset: {self.dataset_folder}")

        # Conjunto para rastrear IDs ya procesados y evitar duplicados
        self.processed_ids = set()
        self._load_processed_ids()

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Crea un logger con salida simultánea a fichero (en la carpeta del
        dataset) y a la consola, ambos con nivel INFO.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger("GencatScraper")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(self.dataset_folder, "scraper.log"), mode='w', encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        return logger

    async def init_browser(self) -> None:
        """Inicializa el navegador Playwright y el contexto de búsqueda.

        Crea instancias de ``playwright``, ``browser`` y ``search_context``
        como atributos de la clase para su uso compartido entre métodos.
        """
        self.logger.info("Iniciando navegador...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.search_context = await self.browser.new_context()
        self.logger.info("Navegador iniciado")

    def _load_processed_ids(self) -> None:
        """Carga los IDs ya procesados desde el CSV existente.

        Si el CSV de salida existe, lee la columna ``id`` para poblar
        ``self.processed_ids`` y evitar reprocesar registros en ejecuciones
        posteriores.
        """
        if os.path.exists(self.csv_path):
            try:
                with open(self.csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'id' in row:
                            self.processed_ids.add(row['id'])
                self.logger.info(f"Cargados {len(self.processed_ids)} IDs ya procesados")
            except Exception as e:
                self.logger.warning(f"No se pudo cargar IDs procesados: {e}")

    async def close(self) -> None:
        """Cierra el contexto, el navegador y la instancia de Playwright.

        Intenta cerrar cada recurso de forma independiente para garantizar
        la limpieza aunque alguno haya fallado previamente.
        """
        try: await self.search_context.close()
        except: pass
        try: await self.browser.close()
        except: pass
        try: await self.playwright.stop()
        except: pass

    async def process_detail(self, url: str) -> dict:
        """Procesa una página de detalle de un elemento patrimonial.

        Abre un contexto efímero de Playwright, navega a la URL, extrae
        el título y la descripción del elemento y comprueba si ya ha sido
        procesado anteriormente.

        Args:
            url: URL de la página de detalle del elemento patrimonial.

        Returns:
            Diccionario con los campos ``id``, ``url`` y ``text``,
            o diccionario vacío si el elemento ya existe o si ocurrió un error.
        """
        detail_context = await self.browser.new_context()
        page = await detail_context.new_page()

        try:
            await page.goto(url, timeout=60000)

            # Extraer el título (usado como ID)
            title_elem = await page.query_selector('h1.page-header, h1')
            if not title_elem:
                record_id = await page.title()
            else:
                record_id = await title_elem.inner_text()

            record_id = record_id.strip()

            # Verificación temprana de duplicados
            if record_id in self.processed_ids:
                self.logger.info(f"Saltando duplicado: {record_id}")
                return {}

            self.logger.info(f"Extrayendo: {record_id}")

            # Extraer la descripción del elemento
            text = ""
            body_elem = await page.query_selector('.description .custom-content, .description, .field-name-body, .field-type-text-with-summary')

            if body_elem:
                text = await body_elem.inner_text()

            text = text.strip()

            if not text:
                self.logger.warning(f"Texto vacío para {url}")

            return {
                "id": record_id,
                "url": url,
                "text": text
            }

        except Exception as e:
            self.logger.error(f"Error procesando detalle {url}: {e}")
            return {}
        finally:
            try: await detail_context.close()
            except: pass

    async def scrape(self) -> None:
        """Navega por el catálogo de patrimonio y procesa todos los elementos.

        Accede al buscador del catálogo Gencat con filtros específicos,
        espera a que carguen los resultados AJAX, extrae todos los enlaces
        a páginas de colección y procesa cada detalle individualmente.
        Incluye aceptación automática de cookies y una pausa de 0,5 segundos
        entre registros para no saturar el servidor.

        Raises:
            Exception: Si se produce un error de navegación general.
        """
        self.logger.info("=== INICIANDO SCRAPING GENCAT ===")
        await self.init_browser()

        page = await self.search_context.new_page()

        # URL base con todos los parámetros de búsqueda necesarios
        base_search_url = "https://patrimoni.gencat.cat/es/descubre/busca"
        params = (
            "field_geofield_distance%5Bdistance%5D=25&"
            "field_geofield_distance%5Bunit%5D=6371&"
            "field_geofield_distance%5Borigin%5D=&"
            "field_scope_tid=All&field_topic_tid=All&"
            "field_services_tid=All&term_node_tid_depth=All&"
            "field_typology_tid=All&field_audience_tid=All&"
            "field_price_range_tid=All"
        )

        try:
            # Gencat carga todos los resultados en una sola página (sin paginación real)
            url = f"{base_search_url}?{params}"
            self.logger.info(f"Navegando a URL de búsqueda (Single Page)...")
            await page.goto(url, timeout=60000)

            # Esperar a que la red se calme tras la carga AJAX
            try:
                await page.wait_for_load_state('networkidle', timeout=30000)
            except:
                self.logger.warning("Timeout esperando networkidle, intentando seguir...")

            # Aceptar cookies si aparece el banner
            try:
                cookie_btn = page.get_by_text("Aceptar todas", exact=False)
                if await cookie_btn.count() > 0 and await cookie_btn.first.is_visible():
                    await cookie_btn.first.click()
                    await asyncio.sleep(1)
            except: pass

            # Esperar a que aparezca el grid de resultados
            try:
                await page.wait_for_selector('#views-bootstrap-grid-1', timeout=30000)
            except:
                self.logger.warning("No se encontró el grid #views-bootstrap-grid-1, buscando enlaces genéricos...")

            # Extraer todos los enlaces de colección
            links = await page.evaluate('''() => {
                let container = document.querySelector('#views-bootstrap-grid-1');
                if (!container) container = document;

                const anchors = Array.from(container.querySelectorAll('a[href*="/coleccion/"]'));
                return anchors.map(a => a.href);
            }''')

            unique_links = list(set(links))
            total_items = len(unique_links)

            if not unique_links:
                self.logger.error("No se encontraron enlaces de colección. Fin.")
            else:
                self.logger.info(f"Encontrados {total_items} items totales para procesar.")

                for i, link in enumerate(unique_links):
                    self.logger.info(f"Procesando {i+1}/{total_items}: {link}")
                    data = await self.process_detail(link)
                    if data and data.get('id'):
                        self.append_to_csv(data)
                        self.processed_ids.add(data['id'])

                    # Pausa para no saturar el servidor
                    await asyncio.sleep(0.5)

        except Exception as e:
            self.logger.error(f"Error en flujo principal: {e}")
        finally:
            await self.close()
            self.postprocess()

    def append_to_csv(self, data: dict) -> None:
        """Añade un nuevo registro al archivo CSV de salida.

        Si el archivo CSV no existe, escribe la cabecera antes de añadir
        la primera fila.

        Args:
            data: Diccionario con los campos ``id``, ``url`` y ``text``.
        """
        file_exists = os.path.exists(self.csv_path)
        keys = ["id", "url", "text"]

        try:
            with open(self.csv_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(data)
        except Exception as e:
            self.logger.error(f"Error escribiendo CSV: {e}")

    def postprocess(self) -> None:
        """Convierte el CSV de salida a formato Parquet.

        Lee el CSV generado y lo escribe como archivo Parquet en la misma
        carpeta del dataset.
        """
        try:
            if os.path.exists(self.csv_path):
                df = pl.read_csv(self.csv_path)
                output_parquet = os.path.join(self.dataset_folder, "output.parquet")
                df.write_parquet(output_parquet)
                self.logger.info(f"Creado parquet en {output_parquet}")
        except Exception as e:
            self.logger.error(f"Error en postprocess: {e}")


if __name__ == "__main__":
    # Crear instancia del recolector de datos
    scraper = GencatScraper(
        config_path="config.yaml",
        folders=["ALIA", "Cataluña"]
    )

    # Ejecutar proceso de recolección
    asyncio.run(scraper.scrape())
