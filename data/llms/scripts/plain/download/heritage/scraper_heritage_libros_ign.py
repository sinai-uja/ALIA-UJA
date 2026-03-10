"""Recolector de datos web para Libros del Instituto Geográfico Nacional.

Este módulo implementa un método que recolecta PDFs de libros digitales del
Instituto Geográfico Nacional (IGN) mediante Playwright. Los datos se
almacenan en formato Parquet para su posterior análisis.

Fuente de datos:
    https://www.ign.es/web/ign/portal/publicaciones-boletines-y-libros-digitales/
    -/consulta-libros/datosPublicaciones

Example:
    Para ejecutar el script directamente::

        $ python scraper_heritage_libros_ign.py

    Para usar la clase programáticamente::

        collector = DataCollector(
            config_path="config.yaml",
            folders=["ALIA", "Libros_Instituto_Geografico_Nacional"],
            url="https://www.ign.es/..."
        )
        collector.execute()

Note:
    Requiere un archivo config.yaml con las credenciales de acceso al disco
    de red donde se almacenarán los datos. También requiere Playwright instalado.
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
    """Recolector de datos web con Playwright para descarga de PDFs del IGN.

    Esta clase gestiona el proceso completo de recolección de PDFs desde
    el catálogo de libros digitales del IGN, navegando a cada página de
    detalle y extrayendo metadatos y enlaces de descarga.

    Attributes:
        dataset_folder: Ruta a la carpeta principal del dataset.
        pdf_folder: Ruta a la carpeta donde se almacenan los PDFs.
        parquet_path: Ruta al archivo Parquet con los metadatos.
        logger: Logger configurado para registrar la ejecución.
        base_url: URL base del catálogo de libros.
        existing_ids: Set de IDs ya existentes en el Parquet.
        downloaded_filenames: Set de nombres de archivo ya descargados.
        records_buffer: Buffer temporal de registros antes de guardar.
    """

    # Configuración de tiempos de espera (en segundos)
    PAGE_LOAD_DELAY = 3
    BETWEEN_ITEMS_DELAY = 2
    DOWNLOAD_TIMEOUT = 120000  # milisegundos

    def __init__(self, config_path: str, folders: list[str], url: str) -> None:
        """Inicializa el recolector de datos.

        Crea las carpetas necesarias, monta el disco de red, configura el
        logger y carga los IDs existentes del archivo Parquet.

        Args:
            config_path: Ruta al archivo de configuración YAML con las
                credenciales de acceso (disk_path, user, password).
            folders: Lista de nombres de carpetas a crear recursivamente
                en el disco de red. El último elemento se usa como nombre
                de la subcarpeta para PDFs.
            url: URL base del catálogo de libros.

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
        self.base_url = url
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
        """
        clean_string = unicodedata.normalize('NFKD', string)
        clean_string = clean_string.encode('ascii', 'ignore').decode('ascii')
        clean_string = re.sub(r'[\\/*?:"<>|]', replacement, clean_string)
        clean_string = re.sub(f'{replacement}+', replacement, clean_string)
        clean_string = clean_string.strip(replacement)
        return clean_string

    async def collect_catalog(self) -> dict:
        """Recorre el catálogo y descarga los PDFs de cada libro.

        Navega a la página del catálogo, obtiene todos los enlaces de libros,
        visita cada página de detalle para extraer metadatos y descarga el PDF.

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
                self.logger.info(f"[CATALOG] Accediendo a: {self.base_url}")
                await page.goto(self.base_url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(self.PAGE_LOAD_DELAY)

                # Obtener todos los enlaces de libros
                book_links = await page.query_selector_all("a.publication.note.tac.tamanio")

                if not book_links:
                    self.logger.warning("[CATALOG] No se encontraron enlaces de libros")
                    return raw_docs

                self.logger.info(f"[CATALOG] Encontrados {len(book_links)} libros")

                # Recolectar las URLs de todos los libros primero
                book_urls = []
                for link in book_links:
                    href = await link.get_attribute("href")
                    if href:
                        # Construir URL completa si es relativa
                        if href.startswith("/"):
                            href = f"https://www.ign.es{href}"
                        book_urls.append(href)

                self.logger.info(f"[CATALOG] URLs de libros recolectadas: {len(book_urls)}")

                # Procesar cada libro
                for idx, book_url in enumerate(book_urls):
                    try:
                        self.logger.info(f"[BOOK {idx+1}/{len(book_urls)}] Procesando: {book_url}")

                        # Navegar a la página de detalle del libro
                        await page.goto(book_url, wait_until="networkidle", timeout=30000)
                        await asyncio.sleep(self.PAGE_LOAD_DELAY)

                        # Extraer metadatos
                        metadata = await self._extract_metadata(page)

                        if not metadata.get("pdf_url"):
                            self.logger.warning(f"[BOOK] No se encontró enlace PDF en {book_url}")
                            continue

                        # Generar identificador desde la URL del PDF
                        pdf_url = metadata["pdf_url"]
                        pdf_filename = Path(pdf_url).stem
                        identifier = self.clean_filename(pdf_filename)

                        if not identifier:
                            identifier = f"libro_ign_{idx}"

                        self.logger.info(f"[BOOK] Identificador: {identifier}")

                        # Verificar si ya existe
                        if identifier in self.existing_ids or identifier in self.downloaded_filenames:
                            self.logger.info(f"[BOOK] {identifier} ya existe. Omitiendo...")
                            continue

                        # Descargar el PDF
                        pdf_path = await self._download_direct(pdf_url, identifier)

                        if pdf_path:
                            raw_docs[identifier] = pdf_path
                            self.downloaded_filenames.add(identifier)

                            # Añadir registro al buffer con metadatos
                            self.append_record({
                                "id": identifier,
                                "url": book_url,
                                "authors": metadata.get("authors", ""),
                                "year": metadata.get("year", ""),
                                "n_pages": metadata.get("n_pages", ""),
                                "description": metadata.get("description", ""),
                                "text": ""
                            })

                        # Pausa entre items
                        await asyncio.sleep(self.BETWEEN_ITEMS_DELAY)

                    except PlaywrightTimeout as e:
                        self.logger.warning(f"[BOOK] Timeout procesando libro {idx}: {e}")
                        continue
                    except Exception as e:
                        self.logger.error(f"[BOOK] Error procesando libro {idx}: {e}")
                        continue

                # Guardar todos los registros
                self.save_to_parquet()

            except Exception as e:
                self.logger.error(f"[CATALOG] Error general: {e}", exc_info=True)

            finally:
                await browser.close()

        return raw_docs

    async def _extract_metadata(self, page) -> dict:
        """Extrae los metadatos de la página de detalle del libro.

        Args:
            page: Página de Playwright activa en la página de detalle.

        Returns:
            Diccionario con los metadatos extraídos:
                - authors: Autor/Autores
                - year: Fecha de edición
                - n_pages: Número de páginas
                - description: Resumen del libro
                - pdf_url: URL del PDF de descarga
        """
        metadata = {
            "authors": "",
            "year": "",
            "n_pages": "",
            "description": "",
            "pdf_url": ""
        }

        try:
            # Obtener el contenedor principal
            content_div = await page.query_selector("div.w75")
            if not content_div:
                content_div = page

            # Extraer todos los párrafos con metadatos
            paragraphs = await content_div.query_selector_all("p")

            for p in paragraphs:
                text_content = await p.text_content()
                if not text_content:
                    continue

                text_content = text_content.strip()

                # Autor/Autores
                if "Autor" in text_content:
                    # Extraer el texto después de ":"
                    match = re.search(r'Autor(?:/Autores)?:\s*(.+)', text_content)
                    if match:
                        metadata["authors"] = match.group(1).strip()

                # Fecha de edición
                elif "Fecha de edición" in text_content:
                    match = re.search(r'Fecha de edición:\s*(\d{4})', text_content)
                    if match:
                        metadata["year"] = match.group(1).strip()

                # Número de páginas
                elif "páginas" in text_content.lower():
                    match = re.search(r'Nº de páginas:\s*(\d+)', text_content)
                    if match:
                        metadata["n_pages"] = match.group(1).strip()

            # Extraer descripción (Resumen del libro)
            # Buscar el span con "Resumen del libro" y obtener el texto siguiente
            resumen_span = await content_div.query_selector("span.publicationsParts")
            if resumen_span:
                parent_p = await resumen_span.evaluate_handle("el => el.parentElement")
                if parent_p:
                    full_text = await parent_p.text_content()
                    if full_text:
                        # Eliminar el título "Resumen del libro" y limpiar
                        description = re.sub(r'Resumen del libro:\s*', '', full_text)
                        metadata["description"] = description.strip()

            # Extraer enlace del PDF
            # Buscar enlaces que contengan .pdf en el href
            pdf_links = await content_div.query_selector_all("a[href*='.pdf']")
            for link in pdf_links:
                href = await link.get_attribute("href")
                if href and ".pdf" in href.lower():
                    metadata["pdf_url"] = href
                    break

            # Si no encontró en el div, buscar en toda la página
            if not metadata["pdf_url"]:
                pdf_links = await page.query_selector_all("a[href*='.pdf']")
                for link in pdf_links:
                    href = await link.get_attribute("href")
                    if href and ".pdf" in href.lower():
                        metadata["pdf_url"] = href
                        break

        except Exception as e:
            self.logger.warning(f"[METADATA] Error extrayendo metadatos: {e}")

        return metadata

    async def _download_direct(self, url: str, identifier: str) -> str:
        """Descarga un PDF directamente usando aiohttp.

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
            self.logger.info(f"[PDF] Archivo {filename} ya existe.")
            return path

        timeout = ClientTimeout(total=180, connect=30)
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

                    self.logger.info(f"[PDF] Descargado: {filename} ({len(content)} bytes)")
                    return path

        except Exception as e:
            self.logger.error(f"[PDF] Error descargando {filename}: {e}")
            return ""

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Inicia la recolección de PDFs de forma asíncrona, navegando por
        el catálogo. Al finalizar, todos los datos quedan guardados
        en el archivo Parquet.
        """
        self.logger.info("=" * 80)
        self.logger.info("[INICIO] Comenzando recolección de Libros IGN")
        self.logger.info("=" * 80)

        asyncio.run(self.collect_catalog())

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
    # URL del catálogo de libros digitales del IGN
    BASE_URL = (
        "https://www.ign.es/web/ign/portal/publicaciones-boletines-y-libros-digitales/"
        "-/consulta-libros/datosPublicaciones"
    )

    # Crear instancia del recolector de datos
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Libros_Instituto_Geografico_Nacional"],
        url=BASE_URL
    )

    # Ejecutar proceso de recolección de datos
    collector.execute()
