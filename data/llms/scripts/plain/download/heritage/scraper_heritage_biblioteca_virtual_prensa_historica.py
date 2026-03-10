"""Recolector de datos web para Biblioteca Virtual de Prensa Histórica.

Este módulo implementa un método que recolecta información sobre revistas
culturales de la Biblioteca Virtual de Prensa Histórica (BVPH) mediante
Playwright. Los datos se extraen navegando por el catálogo de revistas
y descargando los PDFs asociados.

La BVPH contiene:
    - Revistas culturales históricas
    - Publicaciones periódicas digitalizadas
    - Archivos de prensa histórica española

Example:
    Ejecución básica::

        python scraper_heritage_biblioteca_virtual_prensa_historica.py

    Esto navegará por el catálogo de revistas culturales, extraerá
    los metadatos y descargará los PDFs correspondientes.

Attributes:
    BASE_URL (str): URL de la página de búsqueda de la BVPH.

Note:
    Los datos son de acceso público a través del portal de Prensa Histórica
    del Ministerio de Cultura.
    URL: https://prensahistorica.mcu.es
"""

import asyncio
import logging
import os
import re
import unicodedata
from urllib.parse import urljoin

import aiofiles
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


# URL base de búsqueda
BASE_URL = "https://prensahistorica.mcu.es/es/consulta/busqueda.do"


class DataCollector:
    """Recolector de datos web con Playwright para Prensa Histórica.

    Esta clase gestiona el proceso completo de recolección de datos desde
    la Biblioteca Virtual de Prensa Histórica, navegando por las revistas
    culturales y descargando los PDFs.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs descargados.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        main_url: URL principal del catálogo.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Biblioteca_Virtual_Prensa_Historica"],
        ...     url=BASE_URL
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str],
        url: str
    ) -> None:
        """Inicializa el recolector de datos.

        Crea las carpetas necesarias, monta el disco de red, configura el
        logger y carga los IDs existentes del archivo Parquet.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset (ej: ['ALIA', 'Biblioteca_Virtual_Prensa_Historica']).
            url: URL principal del catálogo de búsqueda.

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
            win32net.error: Si falla la conexión al disco de red.
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

        # URL principal
        self.main_url = url

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        # Semáforo para limitar descargas concurrentes
        self.download_semaphore = asyncio.Semaphore(5)

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] PDF folder: {self.pdf_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet.

        Args:
            parquet_path: Ruta al archivo Parquet. Si es None, usa
                self.parquet_path.

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
        """Persiste los registros del buffer en el archivo Parquet.

        Si el archivo Parquet ya existe, concatena los nuevos registros
        al DataFrame existente. Después de guardar, limpia el buffer.
        """
        if not self.records_buffer:
            self.logger.info("No hay registros nuevos para guardar.")
            return

        try:
            new_df = pl.DataFrame(self.records_buffer)

            if os.path.exists(self.parquet_path):
                existing_df = pl.read_parquet(self.parquet_path)

                # Unificar tipos de columnas
                for col in existing_df.columns:
                    if col in new_df.columns:
                        existing_dtype = existing_df.schema[col]
                        new_dtype = new_df.schema[col]

                        if existing_dtype != new_dtype:
                            try:
                                existing_df = existing_df.with_columns(
                                    pl.col(col).cast(new_dtype)
                                )
                            except Exception:
                                pass

                combined_df = pl.concat([existing_df, new_df], how="diagonal_relaxed")
            else:
                combined_df = new_df

            combined_df.write_parquet(self.parquet_path)
            self.logger.info(
                f"Se guardaron {len(self.records_buffer)} registros en {self.parquet_path}"
            )
            self.records_buffer.clear()

        except Exception as e:
            self.logger.error(
                f"No se pudo escribir en el archivo Parquet: {e}"
            )

    @staticmethod
    def clean_filename(name: str, replacement: str = "_") -> str:
        """Limpia un string para usarlo como nombre de archivo válido.

        Args:
            name: Nombre original.
            replacement: Carácter para reemplazar caracteres inválidos.

        Returns:
            Nombre de archivo limpio y seguro.
        """
        clean_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', replacement, clean_name)
        clean_name = re.sub(r'[\\/*?:"<>|]', replacement, clean_name)
        clean_name = re.sub(f'{replacement}+', replacement, clean_name)
        clean_name = clean_name.strip(replacement)
        return clean_name if clean_name else "documento"

    async def download_pdf(self, filename: str, url: str) -> str:
        """Descarga un PDF usando Playwright de forma asíncrona.

        Args:
            filename: Nombre del archivo (sin extensión).
            url: URL directa del archivo PDF.

        Returns:
            Ruta del archivo PDF descargado.

        Raises:
            Exception: Si falla la descarga o el recurso no es un PDF válido.
        """
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        path = os.path.join(self.pdf_folder, filename)

        if os.path.exists(path):
            self.logger.debug(f"[PDF] {filename} ya descargado. Omitiendo...")
            return path

        async with self.download_semaphore:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0",
                    ignore_https_errors=True
                )
                page = await context.new_page()

                try:
                    response = await page.request.get(url)

                    if response.status == 429:
                        self.logger.warning(f"[PDF] Rate limit alcanzado para {filename}. Esperando...")
                        await asyncio.sleep(5)
                        raise Exception("Demasiadas peticiones (429 Too Many Requests)")

                    # Validar que es PDF
                    content_type = response.headers.get("content-type", "").lower()
                    content = await response.body()
                    if "pdf" not in content_type and not content.startswith(b"%PDF"):
                        raise ValueError(f"El recurso en {url} no es un PDF válido")

                    # Guardar en disco
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)

                    self.logger.info(f"[PDF] {filename} descargado correctamente")
                    return path

                except Exception as e:
                    self.logger.error(f"[PDF] Error descargando {filename}: {e}")
                    raise
                finally:
                    await browser.close()

    async def process_journal(self, journal_page: Page, journal_url: str, 
                              journal_id: str, journal_title: str) -> int:
        """Procesa una revista individual extrayendo y descargando PDFs.

        Navega por la estructura de años/meses de la revista y descarga
        cada número en formato PDF.

        Args:
            journal_page: Página de Playwright activa.
            journal_url: URL de la página de la revista.
            journal_id: Identificador de la revista.
            journal_title: Título de la revista.

        Returns:
            Número de PDFs nuevos procesados.
        """
        new_count = 0

        try:
            self.logger.info(f"[REVISTA] Procesando: {journal_title}")
            await journal_page.goto(journal_url, wait_until="load", timeout=30000)
            await asyncio.sleep(2)

            # Obtener información de los años
            year_containers = await journal_page.query_selector_all("div.caja_serie_anio p")
            year_info = []

            for container in year_containers:
                link = await container.query_selector("a")
                if link:
                    year_text = (await link.inner_text()).replace("Año", "").strip()
                else:
                    year_text = (await container.inner_text()).replace("Año", "").strip()

                if year_text:
                    year_info.append({
                        'year': year_text,
                        'has_link': link is not None
                    })

            self.logger.info(f"[REVISTA] {journal_title} - Años encontrados: {len(year_info)}")

            # Procesar cada año
            for year_data in year_info:
                year = year_data['year']
                has_link = year_data['has_link']

                try:
                    # Si tiene enlace, hacer click para expandir
                    if has_link:
                        year_containers = await journal_page.query_selector_all("div.caja_serie_anio p")

                        for container in year_containers:
                            container_text = (await container.inner_text()).replace("Año", "").strip()
                            if container_text == year:
                                link = await container.query_selector("a")
                                if link:
                                    await link.click()
                                    await journal_page.wait_for_timeout(1000)
                                    break

                    # Esperar a que aparezcan los meses
                    try:
                        await journal_page.wait_for_selector(
                            "div.caja_serie_numeros ol#arbol > li", 
                            timeout=5000
                        )
                    except PlaywrightTimeout:
                        self.logger.warning(f"[REVISTA] No se encontraron meses para año {year}")
                        continue

                    # Obtener meses
                    month_containers = await journal_page.query_selector_all(
                        "div.caja_serie_numeros ol#arbol > li"
                    )

                    for month_container in month_containers:
                        month_raw = await month_container.inner_text()
                        month = re.sub(r"\(\d+\)", "", month_raw).strip()

                        # Obtener números del mes
                        number_containers = await month_container.query_selector_all("li.arbol_hoja")

                        for i, number_container in enumerate(number_containers):
                            try:
                                pdf_link = await number_container.query_selector("a.enlace_externo")
                                if not pdf_link:
                                    continue

                                href = await pdf_link.get_attribute("href")
                                if not href:
                                    continue

                                item_id = f"{self.clean_filename(journal_id)}_{year}_{month}_{i}"

                                # Verificar si ya existe
                                if item_id in self.existing_ids:
                                    self.logger.debug(f"[Skip] {item_id} ya procesado")
                                    continue

                                pdf_url = urljoin(journal_page.url, href)

                                # Extraer licencia
                                license_link = await number_container.query_selector("li.copyright a")
                                license_text = await license_link.get_attribute("href") if license_link else ""

                                # Descargar PDF
                                try:
                                    pdf_path = await self.download_pdf(item_id, pdf_url)

                                    # Añadir registro
                                    self.append_record({
                                        "id": item_id,
                                        "journal": journal_title,
                                        "year": year,
                                        "month": month,
                                        "license": license_text,
                                        "pdf_url": pdf_url,
                                        "pdf_path": pdf_path,
                                        "text": ""  # Se rellenará en postproceso con OCR
                                    })

                                    self.existing_ids.add(item_id)
                                    new_count += 1

                                except Exception as e:
                                    self.logger.error(f"[PDF] Error descargando {item_id}: {e}")

                            except Exception as e:
                                self.logger.error(f"[ERROR] Número {i} de {month}/{year}: {e}")

                except Exception as e:
                    self.logger.error(f"[ERROR] Año {year}: {e}")

            self.logger.info(f"[REVISTA] {journal_title} completada: {new_count} nuevos")

        except Exception as e:
            self.logger.error(f"[ERROR] process_journal {journal_title}: {e}")

        return new_count

    async def collect_catalog(self) -> dict:
        """Navega por el catálogo y procesa todas las revistas culturales.

        Returns:
            Diccionario con estadísticas de la recolección.
        """
        stats = {
            "pages_processed": 0,
            "journals_found": 0,
            "pdfs_new": 0,
            "errors": 0
        }
        save_interval = 50

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                self.logger.info("[NAVEGACIÓN] Accediendo a la página de búsqueda...")
                await page.goto(self.main_url, wait_until="domcontentloaded", timeout=60000)

                # Seleccionar checkbox de Revistas Culturales
                self.logger.info("[NAVEGACIÓN] Seleccionando 'Revistas Culturales'...")
                checkbox = page.locator("#secc_ARCE")
                await checkbox.wait_for(timeout=10000)
                await checkbox.check(force=True)
                await asyncio.sleep(1)

                # Pulsar botón buscar
                search_button = page.locator("input#boton_buscar.submit_boton")
                await search_button.wait_for(timeout=10000)
                await search_button.click()

                await page.wait_for_load_state("networkidle", timeout=60000)
                await asyncio.sleep(2)

                self.logger.info(f"[NAVEGACIÓN] Búsqueda completada. URL: {page.url}")

                # Navegar por páginas de resultados
                page_number = 1

                while True:
                    self.logger.info(f"[PAGINACIÓN] Procesando página {page_number}")

                    journals = await page.query_selector_all('div.registro_bib')
                    stats["journals_found"] += len(journals)
                    self.logger.info(f"[RESULTADOS] {len(journals)} revistas en página {page_number}")

                    for idx, journal in enumerate(journals, 1):
                        try:
                            link = await journal.query_selector("p a")
                            if link:
                                title_elem = await journal.query_selector("span.autor bdi")
                                id_elem = await journal.query_selector("span.titulo bdi")

                                title = await title_elem.inner_text() if title_elem else f"Revista_{idx}"
                                item_id = await id_elem.inner_text() if id_elem else f"ID_{idx}"
                                url = await link.get_attribute("href")
                                publications_url = urljoin(page.url, url)

                                # Crear nueva página para la revista
                                journal_page = await context.new_page()
                                new_count = await self.process_journal(
                                    journal_page, publications_url, item_id, title
                                )
                                stats["pdfs_new"] += new_count
                                await journal_page.close()

                                # Guardar incrementalmente
                                if len(self.records_buffer) >= save_interval:
                                    self.save_to_parquet()

                        except Exception as e:
                            self.logger.error(f"[Error revista {idx}]: {e}")
                            stats["errors"] += 1

                    # Buscar botón siguiente
                    next_button_selector = f"span.boton_pagina{page_number + 1} a"
                    next_button = page.locator(next_button_selector).first

                    if not await next_button.count():
                        self.logger.info("[PAGINACIÓN] No hay más páginas. Finalizando.")
                        break

                    await next_button.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(1)

                    page_number += 1
                    stats["pages_processed"] = page_number

            except Exception as e:
                self.logger.error(f"[NAVEGACIÓN] Error general: {e}")
                stats["errors"] += 1
            finally:
                await page.close()
                await context.close()
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Inicia la navegación por el catálogo y descarga los PDFs.
        Al finalizar, todos los metadatos quedan guardados en Parquet.
        """
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE PRENSA HISTÓRICA")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_catalog())

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Páginas procesadas: {stats['pages_processed']}")
        self.logger.info(f"  Revistas encontradas: {stats['journals_found']}")
        self.logger.info(f"  PDFs nuevos: {stats['pdfs_new']}")
        self.logger.info(f"  Errores: {stats['errors']}")
        self.logger.info("=" * 60)

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
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
    # Crear instancia del recolector de datos
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Biblioteca_Virtual_Prensa_Historica"],
        url=BASE_URL
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

        # Distribución por revista
        print(f"\n📚 DISTRIBUCIÓN POR REVISTA:")
        print("-" * 60)
        journal_counts = df.group_by("journal").count().sort("count", descending=True)
        for row in journal_counts.head(10).iter_rows(named=True):
            print(f"   {row['journal'][:40]:40s}: {row['count']:6d}")

        # Análisis de valores nulos
        print(f"\n📋 ANÁLISIS DE VALORES NULOS:")
        print("-" * 60)
        for col in df.columns:
            null_count = df.filter(pl.col(col).is_null()).height
            pct = (null_count / len(df)) * 100 if len(df) > 0 else 0
            print(f"   {col:15s}: {null_count:6d} nulos ({pct:5.1f}%)")

        # Análisis de duplicados
        print(f"\n🔄 ANÁLISIS DE DUPLICADOS:")
        print("-" * 60)
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        # Distribución por año
        print(f"\n📅 DISTRIBUCIÓN POR AÑO (top 10):")
        print("-" * 60)
        year_counts = df.group_by("year").count().sort("count", descending=True)
        for row in year_counts.head(10).iter_rows(named=True):
            print(f"   {row['year']:15s}: {row['count']:6d}")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
