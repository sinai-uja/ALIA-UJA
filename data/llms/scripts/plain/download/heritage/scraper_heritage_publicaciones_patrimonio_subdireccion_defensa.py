"""Recolector de datos web para Publicaciones Patrimonio Subdireccion Defensa.

Este módulo implementa un método que recolecta PDFs gratuitos de Historia y
Cultura del portal de publicaciones del Ministerio de Defensa mediante
Playwright. Los datos se almacenan en formato Parquet para su posterior análisis.

Fuentes de datos:
    - https://publicaciones.defensa.gob.es/libros/categorías/historia-y-cultura/idioma/español.html
    - https://publicaciones.defensa.gob.es/ebooks/categorías/historia-y-cultura/idioma/español/page/1.html
    - https://publicaciones.defensa.gob.es/pdf/categorías/historia-y-cultura/idioma/español/page/1.html

Example:
    Para ejecutar el script directamente::

        $ python scraper_heritage_publicaciones_patrimonio_subdireccion_defensa.py

    Para usar la clase programáticamente::

        collector = DataCollector(
            config_path="config.yaml",
            folders=["ALIA", "Publicaciones_Patrimonio_Subdireccion_Defensa"],
            urls=[...]
        )
        collector.execute()

Note:
    Requiere un archivo config.yaml con las credenciales de acceso al disco
    de red donde se almacenarán los datos. También requiere Playwright instalado.
    Solo descarga publicaciones marcadas como "gratis" en el precio.
"""

import asyncio
import logging
import os
import re
import unicodedata
from pathlib import Path

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


class DataCollector:
    """Recolector de datos web con Playwright para descarga de PDFs gratuitos.

    Esta clase gestiona el proceso completo de recolección de PDFs desde
    el catálogo de Publicaciones de Defensa, navegando por las páginas
    de libros, ebooks y PDFs, descargando solo los gratuitos.

    Attributes:
        dataset_folder: Ruta a la carpeta principal del dataset.
        pdf_folder: Ruta a la carpeta donde se almacenan los PDFs.
        parquet_path: Ruta al archivo Parquet con los metadatos.
        logger: Logger configurado para registrar la ejecución.
        source_urls: Lista de URLs base para las distintas categorías.
        existing_ids: Set de IDs ya existentes en el Parquet.
        downloaded_filenames: Set de nombres de archivo ya descargados.
        records_buffer: Buffer temporal de registros antes de guardar.
    """

    # Configuración de tiempos de espera (en segundos)
    PAGE_LOAD_DELAY = 3
    BETWEEN_ITEMS_DELAY = 2
    BETWEEN_PAGES_DELAY = 4
    DOWNLOAD_TIMEOUT = 90000  # milisegundos

    def __init__(self, config_path: str, folders: list[str], urls: list[str]) -> None:
        """Inicializa el recolector de datos.

        Crea las carpetas necesarias, monta el disco de red, configura el
        logger y carga los IDs existentes del archivo Parquet.

        Args:
            config_path: Ruta al archivo de configuración YAML con las
                credenciales de acceso (disk_path, user, password).
            folders: Lista de nombres de carpetas a crear recursivamente
                en el disco de red. El último elemento se usa como nombre
                de la subcarpeta para PDFs.
            urls: Lista de URLs base de las categorías a recolectar.

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
            win32net.error: Si falla la conexión al disco de red.
        """
        with open(config_path, 'r') as f:
            try:
                config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise RuntimeError(
                    f"No se pudo cargar el archivo de configuración {config_path}: {e}"
                )

        netresource = {
            'remote': config["disk_path"],
            'user': config["user"],
            'password': config["password"],
        }
        win32net.NetUseAdd(None, 2, netresource)

        self.dataset_folder = os.path.join(config["disk_path"], *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)
        self.pdf_folder = os.path.join(self.dataset_folder, folders[-1])
        os.makedirs(self.pdf_folder, exist_ok=True)

        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")
        self.logger = self.setup_logger()
        self.source_urls = urls
        self.existing_ids = self.get_existing_ids(self.parquet_path)
        self.downloaded_filenames = self._get_existing_filenames()
        self.records_buffer = []

    def _get_existing_filenames(self) -> set:
        """Obtiene los nombres de archivos PDF ya descargados.

        Returns:
            Conjunto con los nombres de archivo (sin extensión) ya existentes.
        """
        existing = set()
        if os.path.exists(self.pdf_folder):
            for f in Path(self.pdf_folder).glob("*.pdf"):
                existing.add(f.stem)
        self.logger.info(f"[PDF] {len(existing)} archivos PDF existentes en carpeta")
        return existing

    def append_record(self, record_data: dict) -> None:
        """Añade un nuevo registro al buffer en memoria.

        El registro se almacena temporalmente hasta que se llame a
        ``save_to_parquet()`` para persistir los datos.

        Args:
            record_data: Diccionario con los campos del registro. Debe
                contener al menos la clave 'id' como identificador único.
        """
        self.records_buffer.append(record_data)
        self.logger.info(f"Registro con ID {record_data['id']} añadido al buffer.")

    def save_to_parquet(self) -> None:
        """Persiste los registros del buffer en el archivo Parquet.

        Si el archivo Parquet ya existe, concatena los nuevos registros
        al DataFrame existente. Después de guardar, limpia el buffer.

        Note:
            Este método es idempotente respecto a los datos: si el buffer
            está vacío, no realiza ninguna operación.
        """
        if not self.records_buffer:
            self.logger.info("No hay registros nuevos para guardar.")
            return

        try:
            new_df = pl.DataFrame(self.records_buffer)

            if os.path.exists(self.parquet_path):
                existing_df = pl.read_parquet(self.parquet_path)
                combined_df = pl.concat([existing_df, new_df])
            else:
                combined_df = new_df

            combined_df.write_parquet(self.parquet_path)
            self.logger.info(
                f"Se guardaron {len(self.records_buffer)} registros en {self.parquet_path}"
            )
            self.records_buffer.clear()

        except Exception as e:
            self.logger.error(
                f"No se pudo escribir en el archivo Parquet {self.parquet_path}: {e}"
            )

    @staticmethod
    def clean_filename(string: str, replacement: str = "_") -> str:
        """Convierte una cadena en un nombre de archivo válido para Windows.

        Normaliza la cadena Unicode a ASCII, elimina caracteres no permitidos
        en nombres de archivo de Windows y limpia duplicados del carácter
        de reemplazo.

        Args:
            string: Cadena de texto a limpiar.
            replacement: Carácter para sustituir caracteres inválidos.
                Por defecto es '_'.

        Returns:
            Cadena de texto válida como nombre de archivo.

        Example:
            >>> DataCollector.clean_filename("Revista Nº 123/2024")
            'Revista_No_123_2024'
        """
        clean_string = unicodedata.normalize('NFKD', string)
        clean_string = clean_string.encode('ascii', 'ignore').decode('ascii')
        clean_string = re.sub(r'[\\/*?:"<>|]', replacement, clean_string)
        clean_string = re.sub(f'{replacement}+', replacement, clean_string)
        clean_string = clean_string.strip(replacement)
        return clean_string

    async def collect_all_sources(self) -> dict:
        """Recorre todas las fuentes y descarga los PDFs gratuitos.

        Navega por todas las páginas de libros, ebooks y pdfs, verifica
        que sean gratuitos y descarga el PDF correspondiente.

        Returns:
            Diccionario con los identificadores como claves y las rutas
            de los PDFs descargados como valores.
        """
        raw_docs = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                accept_downloads=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            try:
                for source_url in self.source_urls:
                    self.logger.info(f"[SOURCE] Procesando fuente: {source_url}")
                    docs = await self._collect_source(page, source_url)
                    raw_docs.update(docs)

            except Exception as e:
                self.logger.error(f"[COLLECT] Error general: {e}", exc_info=True)

            finally:
                await browser.close()

        return raw_docs

    async def _collect_source(self, page, base_url: str) -> dict:
        """Procesa una fuente específica (libros, ebooks o pdf).

        Args:
            page: Página de Playwright activa.
            base_url: URL base de la categoría.

        Returns:
            Diccionario con identificadores y rutas de PDFs.
        """
        raw_docs = {}
        page_num = 1
        has_more_pages = True
        previous_page_ids = set()  # IDs de la página anterior para detectar duplicados
        max_pages = 100  # Límite de seguridad

        # Detectar si la URL tiene paginación
        has_pagination = "/page/" in base_url

        while has_more_pages and page_num <= max_pages:
            # Construir URL de la página actual
            if has_pagination:
                # Reemplazar el número de página en la URL
                catalog_url = re.sub(r'/page/\d+', f'/page/{page_num}', base_url)
            else:
                # Primera página sin paginación, luego agregar /page/N
                if page_num == 1:
                    catalog_url = base_url
                else:
                    # Insertar paginación antes de .html
                    catalog_url = base_url.replace('.html', f'/page/{page_num}.html')

            self.logger.info(f"[CATALOG] Página {page_num}: {catalog_url}")

            try:
                await page.goto(catalog_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(self.PAGE_LOAD_DELAY)
            except PlaywrightTimeout:
                self.logger.warning(f"[CATALOG] Timeout en página {page_num}")
                break

            # Buscar todos los productos en esta página
            product_blocks = await page.query_selector_all("div.product-preview")

            if not product_blocks:
                self.logger.info(f"[CATALOG] No hay más productos en página {page_num}")
                has_more_pages = False
                break

            self.logger.info(f"[CATALOG] Encontrados {len(product_blocks)} productos")

            # PRIMERO: Recolectar TODOS los identificadores de productos de esta página
            # (independientemente de si son gratis o no) para detectar paginación infinita
            current_page_ids = []
            for product in product_blocks:
                try:
                    # Usar el enlace del producto como identificador único
                    product_link = await product.query_selector("h5.product-name a")
                    if not product_link:
                        product_link = await product.query_selector(".product-name a")
                    if not product_link:
                        product_link = await product.query_selector("a")
                    
                    if product_link:
                        href = await product_link.get_attribute("href")
                        if href:
                            current_page_ids.append(href)
                except Exception:
                    pass

            self.logger.info(f"[CATALOG] IDs de página: {len(current_page_ids)} productos identificados")

            # Detectar paginación infinita: si los productos son idénticos a la página anterior
            if current_page_ids and current_page_ids == previous_page_ids:
                self.logger.info(f"[CATALOG] Paginación infinita detectada: página {page_num} tiene los mismos productos que página {page_num - 1}")
                has_more_pages = False
                break

            # Guardar IDs de esta página para la próxima comparación
            previous_page_ids = current_page_ids.copy()

            # AHORA: Procesar solo los productos gratuitos
            new_products_found = 0

            for idx, product in enumerate(product_blocks):
                try:
                    # Verificar si es gratis
                    price_element = await product.query_selector("div.price-box span.price")
                    if not price_element:
                        continue

                    price_text = await price_element.text_content()
                    if not price_text or "gratis" not in price_text.lower():
                        continue

                    self.logger.info(f"[PRODUCT] Producto {idx} es GRATIS")

                    # Buscar enlace de descarga PRIMERO para obtener el nombre del archivo
                    download_link = await product.query_selector("div.cart_box_but a")
                    if not download_link:
                        self.logger.warning(f"[PRODUCT] No hay enlace de descarga para producto {idx}")
                        continue

                    download_href = await download_link.get_attribute("href")
                    if not download_href:
                        continue

                    # Extraer nombre del archivo PDF de la URL como identificador primario
                    pdf_filename = Path(download_href).stem
                    if pdf_filename:
                        identifier = pdf_filename
                    else:
                        # Fallback: intentar obtener título del producto
                        title_element = await product.query_selector("h5.product-name a")
                        if not title_element:
                            title_element = await product.query_selector(".product-name a")
                        if not title_element:
                            title_element = await product.query_selector("a.product-name")
                        if not title_element:
                            title_element = await product.query_selector("h5 a")
                        
                        if title_element:
                            title = await title_element.text_content()
                            identifier = self.clean_filename(title.strip()) if title else f"documento_{idx}"
                        else:
                            identifier = f"documento_{idx}"

                    self.logger.info(f"[PRODUCT] Identificador: {identifier}")

                    # Verificar si ya existe (evitar duplicados entre fuentes)
                    if identifier in self.existing_ids or identifier in self.downloaded_filenames:
                        self.logger.info(f"[PRODUCT] {identifier} ya existe. Omitiendo...")
                        continue

                    new_products_found += 1

                    # Obtener URL de la página del producto
                    product_link = await product.query_selector("h5.product-name a")
                    if not product_link:
                        product_link = await product.query_selector(".product-name a")
                    if not product_link:
                        product_link = await product.query_selector("a.product-name")
                    
                    product_url = ""
                    if product_link:
                        product_url = await product_link.get_attribute("href") or ""

                    # Descargar el PDF (usar descarga directa como método principal)
                    pdf_path = await self._download_direct(download_href, identifier)

                    if pdf_path:
                        raw_docs[identifier] = pdf_path
                        self.downloaded_filenames.add(identifier)

                        # Añadir registro al buffer
                        self.append_record({
                            "id": identifier,
                            "url": product_url or download_href,
                            "text": ""
                        })

                    # Pausa entre items
                    await asyncio.sleep(self.BETWEEN_ITEMS_DELAY)

                except Exception as e:
                    self.logger.error(f"[PRODUCT] Error procesando producto {idx}: {e}")
                    continue

            # Guardar después de cada página del catálogo
            self.save_to_parquet()

            # Siguiente página
            page_num += 1

            # Pausa entre páginas del catálogo
            await asyncio.sleep(self.BETWEEN_PAGES_DELAY)

        if page_num > max_pages:
            self.logger.warning(f"[CATALOG] Alcanzado límite máximo de {max_pages} páginas")

        return raw_docs

    async def download_pdf(self, page, url: str, identifier: str) -> str:
        """Descarga un PDF desde una URL.

        Args:
            page: Página de Playwright activa.
            url: URL del archivo PDF.
            identifier: Identificador para el nombre del archivo.

        Returns:
            Ruta al archivo PDF descargado, o cadena vacía si falla.
        """
        filename = f"{identifier}.pdf"
        path = os.path.join(self.pdf_folder, filename)

        if os.path.exists(path):
            self.logger.info(f"[PDF] Archivo {filename} ya existe. Omitiendo...")
            return path

        try:
            # Navegar a la URL de descarga
            async with page.expect_download(timeout=self.DOWNLOAD_TIMEOUT) as download_info:
                await page.goto(url, wait_until="commit")

            download = await download_info.value

            # Guardar el archivo
            await download.save_as(path)

            file_size = os.path.getsize(path)
            self.logger.info(f"[PDF] Descargado {filename} ({file_size} bytes)")

            return path

        except PlaywrightTimeout:
            # Intentar descarga directa como alternativa
            self.logger.warning(f"[PDF] Timeout en descarga de {filename}, intentando método directo")
            return await self._download_direct(url, identifier)

        except Exception as e:
            self.logger.error(f"[PDF] Error descargando {filename}: {e}")
            return await self._download_direct(url, identifier)

    async def _download_direct(self, url: str, identifier: str) -> str:
        """Descarga un PDF directamente usando aiohttp como fallback.

        Args:
            url: URL directa al archivo PDF.
            identifier: Identificador para el nombre del archivo.

        Returns:
            Ruta al archivo PDF descargado, o cadena vacía si falla.
        """
        import aiohttp
        from aiohttp import ClientTimeout

        filename = f"{identifier}.pdf"
        path = os.path.join(self.pdf_folder, filename)

        if os.path.exists(path):
            return path

        timeout = ClientTimeout(total=120, connect=30)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as response:
                    response.raise_for_status()

                    content = await response.read()

                    with open(path, 'wb') as f:
                        f.write(content)

                    self.logger.info(f"[PDF] Descarga directa: {filename} ({len(content)} bytes)")
                    return path

        except Exception as e:
            self.logger.error(f"[PDF] Error en descarga directa de {filename}: {e}")
            return ""

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Inicia la recolección de PDFs de forma asíncrona, navegando por
        todas las fuentes y páginas. Al finalizar, todos los datos
        quedan guardados en el archivo Parquet.
        """
        self.logger.info("=" * 80)
        self.logger.info("[INICIO] Comenzando recolección de Publicaciones Patrimonio Defensa")
        self.logger.info("=" * 80)

        asyncio.run(self.collect_all_sources())

        # Guardar registros pendientes
        self.save_to_parquet()

        # Resumen final
        self.logger.info("=" * 80)
        self.logger.info("[RESUMEN FINAL]")
        self.logger.info("=" * 80)

        if os.path.exists(self.parquet_path):
            df = pl.read_parquet(self.parquet_path)
            self.logger.info(f"Total de registros en el dataset: {len(df)}")

        pdf_count = len(list(Path(self.pdf_folder).glob("*.pdf")))
        self.logger.info(f"Total de PDFs descargados: {pdf_count}")

    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet.

        Carga el archivo Parquet y extrae la columna 'id' para crear
        un conjunto de identificadores. Se usa para evitar duplicados
        durante la recolección.

        Args:
            parquet_path: Ruta al archivo Parquet. Si es None, usa
                ``self.parquet_path``.

        Returns:
            Conjunto (set) con los IDs existentes. Retorna conjunto
            vacío si el archivo no existe o hay error de lectura.
        """
        if parquet_path is None:
            parquet_path = self.parquet_path

        existing_ids = set()
        if os.path.exists(parquet_path):
            try:
                df = pl.read_parquet(parquet_path)
                if 'id' in df.columns:
                    existing_ids = set(df['id'].to_list())
                    self.logger.info(f"[Parquet] {len(existing_ids)} IDs existentes cargados")
            except Exception as e:
                self.logger.warning(f"[Parquet] Error al leer IDs existentes: {e}")
        return existing_ids

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Crea un logger con dos handlers:
            - FileHandler: Escribe en archivo .log en la carpeta del dataset.
            - StreamHandler: Muestra mensajes en consola.

        El archivo de log usa modo 'append' para preservar logs de
        ejecuciones anteriores.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger(os.path.basename(self.dataset_folder))
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
    # URLs de las tres fuentes de datos
    SOURCE_URLS = [
        "https://publicaciones.defensa.gob.es/libros/categorías/historia-y-cultura/idioma/español.html",
        "https://publicaciones.defensa.gob.es/ebooks/categorías/historia-y-cultura/idioma/español/page/1.html",
        "https://publicaciones.defensa.gob.es/pdf/categorías/historia-y-cultura/idioma/español/page/1.html",
    ]

    # Crear instancia del recolector de datos
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Publicaciones_Patrimonio_Subdireccion_Defensa"],
        urls=SOURCE_URLS
    )

    # Ejecutar proceso de recolección de datos
    collector.execute()
