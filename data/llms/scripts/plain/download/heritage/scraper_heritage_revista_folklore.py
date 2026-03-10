"""Recolector de datos web para la Revista Folklore.

Este módulo implementa un método que recolecta artículos de la Revista 
Folklore de la Fundación Joaquín Díaz mediante Playwright. Los datos
se extraen navegando por los índices anuales y descargando los PDFs
de cada artículo.

La Revista Folklore contiene:
    - Artículos sobre tradición oral española
    - Estudios etnográficos y antropológicos
    - Documentación de costumbres y patrimonio inmaterial

Example:
    Ejecución básica::

        python scraper_heritage_revista_folklore.py

    Esto navegará por todos los años disponibles (1980-2025),
    descargará los PDFs y generará un archivo Parquet.

Attributes:
    BASE_URL (str): URL base del índice anual de la revista.
    YEAR_RANGE (tuple): Rango de años a procesar (inicio, fin).

Note:
    Los artículos están disponibles en acceso abierto a través del
    portal de la Fundación Joaquín Díaz.
    URL: https://funjdiaz.net/folklore/
"""

import asyncio
import logging
import os
from urllib.parse import urlparse

import aiofiles
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


# URL base del índice anual
BASE_URL = "https://funjdiaz.net/folklore/indice.php?an="
YEAR_RANGE = (1980, 2026)


class DataCollector:
    """Recolector de datos web con Playwright para Revista Folklore.

    Esta clase gestiona el proceso completo de recolección de datos desde
    la Revista Folklore, navegando por los índices anuales y descargando
    los PDFs de cada artículo.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs descargados.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        main_url: URL base del índice.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Revista_Folklore"],
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

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset.
            url: URL base del índice anual.

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

        # URL base
        self.main_url = url

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

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
            self.logger.error(f"No se pudo escribir en el archivo Parquet: {e}")

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

            finally:
                await browser.close()

    async def collect_year(self, year: str) -> int:
        """Recolecta todos los artículos de un año específico.

        Navega al índice del año, obtiene todos los enlaces PDF
        y los descarga.

        Args:
            year: Año a procesar (ej: "2020").

        Returns:
            Número de artículos nuevos procesados.
        """
        new_count = 0
        save_interval = 50

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                url = f"{self.main_url}{year}"
                self.logger.info(f"[Año {year}] Navegando a {url}")
                await page.goto(url, wait_until="load", timeout=30000)
                await asyncio.sleep(1)

                # Obtener todos los enlaces a PDFs
                pdf_links = await page.query_selector_all('div.row a[target="_blank"]')
                pdf_urls = [await link.get_attribute('href') for link in pdf_links]

                self.logger.info(f"[Año {year}] Encontrados {len(pdf_urls)} artículos")

                for pdf_url in pdf_urls:
                    try:
                        # Extraer ID del nombre del archivo
                        parsed = urlparse(pdf_url)
                        item_id = os.path.basename(parsed.path)

                        # Saltar si ya existe
                        if item_id in self.existing_ids:
                            self.logger.debug(f"[Skip] {item_id} ya existe")
                            continue

                        # Descargar PDF
                        pdf_path = await self.download_pdf(item_id, pdf_url)

                        # Añadir registro
                        self.append_record({
                            "id": item_id,
                            "year": year,
                            "url": pdf_url,
                            "pdf_path": pdf_path,
                            "text": ""  # Se rellenará en postproceso con OCR
                        })

                        self.existing_ids.add(item_id)
                        new_count += 1

                        # Guardar incrementalmente
                        if len(self.records_buffer) >= save_interval:
                            self.save_to_parquet()

                    except Exception as e:
                        self.logger.error(f"[Error] Descargando {pdf_url}: {e}")
                        await asyncio.sleep(2)

            except PlaywrightTimeout:
                self.logger.warning(f"[Timeout] Año {year}")
            except Exception as e:
                self.logger.error(f"[Error] Año {year}: {e}")
            finally:
                await page.close()
                await context.close()
                await browser.close()

        return new_count

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Itera sobre todos los años configurados y descarga los
        artículos correspondientes.
        """
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE REVISTA FOLKLORE")
        self.logger.info("=" * 60)

        total_new = 0
        start_year, end_year = YEAR_RANGE

        for year in range(start_year, end_year):
            count = asyncio.run(self.collect_year(str(year)))
            total_new += count

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Años procesados: {end_year - start_year}")
        self.logger.info(f"  Artículos nuevos: {total_new}")
        self.logger.info("=" * 60)

    @staticmethod
    async def safe_attr(page: Page, selector: str, attr: str) -> str:
        """Extrae un atributo de un elemento HTML de forma segura.

        Args:
            page: Página de Playwright activa.
            selector: Selector CSS del elemento.
            attr: Nombre del atributo a extraer.

        Returns:
            Valor del atributo o cadena vacía si no existe.
        """
        el = await page.query_selector(selector)
        return await el.get_attribute(attr) if el else ""

    @staticmethod
    async def safe_inner_text(page: Page, selector: str) -> str:
        """Extrae el texto interno de un elemento HTML de forma segura.

        Args:
            page: Página de Playwright activa.
            selector: Selector CSS del elemento.

        Returns:
            Texto interno del elemento o cadena vacía si no existe.
        """
        el = await page.query_selector(selector)
        return await el.inner_text() if el else ""

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
        folders=["ALIA", "Revista_Folklore"],
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

        # Distribución por año
        print(f"\n📅 DISTRIBUCIÓN POR AÑO:")
        print("-" * 60)
        year_counts = df.group_by("year").count().sort("year")
        for row in year_counts.iter_rows(named=True):
            print(f"   {row['year']}: {row['count']:6d}")

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

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
