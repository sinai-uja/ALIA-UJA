"""Recolector de datos para Revista Otarq.

Este módulo implementa un método que recolecta artículos de la
Revista Otarq (Otras Arqueologías). Los PDFs se descargan
y los metadatos se almacenan en Parquet.

La Revista Otarq es:
    - Revista de Arqueología de acceso abierto
    - Publicada por JAS Arqueología

Example:
    Ejecución básica::

        python scraper_heritage_revista_otarq.py

    Esto navegará por el archivo de la revista, descargará PDFs
    y generará un archivo Parquet con metadatos.

Attributes:
    ARCHIVE_URL (str): URL del archivo de números de la revista.

Note:
    Los datos son de acceso abierto.
    URL: http://revistas.jasarqueologia.es/index.php/otarq/issue/archive
"""

import asyncio
import logging
import os

import aiofiles
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


# URL del archivo de la revista
ARCHIVE_URL = "http://revistas.jasarqueologia.es/index.php/otarq/issue/archive"


class DataCollector:
    """Recolector de datos para Revista Otarq.

    Esta clase gestiona el proceso completo de recolección de datos
    desde la revista Otarq, descargando PDFs y almacenando metadatos.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        main_url: URL del archivo de la revista.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Revista_Otarq"]
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
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset.
            url: URL del archivo de la revista. Si es None, usa ARCHIVE_URL.

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

        # Carpeta para PDFs
        self.pdf_folder = os.path.join(self.dataset_folder, "pdf")
        os.makedirs(self.pdf_folder, exist_ok=True)

        # Rutas de archivos
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # Buffer de registros
        self.records_buffer: list[dict] = []

        # URL principal
        self.main_url = url or ARCHIVE_URL

        # Logger
        self.logger = self.setup_logger()

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] PDF folder: {self.pdf_folder}")
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

    async def download_pdf(self, filename: str, url: str) -> str:
        """Descarga un PDF usando Playwright.

        Args:
            filename: Nombre del archivo (sin extensión).
            url: URL del PDF.

        Returns:
            Ruta del archivo descargado.
        """
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        path = os.path.join(self.pdf_folder, filename)

        if os.path.exists(path):
            self.logger.debug(f"[PDF] {filename} ya existe. Omitiendo...")
            return path

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0",
                ignore_https_errors=True
            )
            page = await context.new_page()

            try:
                response = await page.request.get(url, timeout=60000)

                if response.status == 429:
                    raise Exception("Too Many Requests (429)")

                content_type = (response.headers.get("content-type") or "").lower()
                content = await response.body()

                if "pdf" in content_type or content.startswith(b"%PDF"):
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)
                    self.logger.info(f"[PDF] {filename} descargado")
                    return path
                else:
                    raise ValueError(f"No es un PDF válido: {url}")

            except PlaywrightTimeout:
                self.logger.warning(f"[Timeout] {url}")
                raise
            except Exception as e:
                self.logger.error(f"[Error] {url}: {e}")
                raise
            finally:
                await browser.close()

    @staticmethod
    async def safe_attr(page: Page, selector: str, attr: str) -> str:
        """Obtiene un atributo de un elemento de forma segura.

        Args:
            page: Página de Playwright.
            selector: Selector CSS del elemento.
            attr: Nombre del atributo.

        Returns:
            Valor del atributo o cadena vacía.
        """
        el = await page.query_selector(selector)
        return await el.get_attribute(attr) if el else ""

    @staticmethod
    async def safe_inner_text(page: Page, selector: str) -> str:
        """Obtiene el texto interior de un elemento de forma segura.

        Args:
            page: Página de Playwright.
            selector: Selector CSS del elemento.

        Returns:
            Texto interior o cadena vacía.
        """
        el = await page.query_selector(selector)
        return (await el.inner_text()).strip() if el else ""

    async def collect_articles(self) -> dict:
        """Recopila artículos del archivo de la revista.

        Returns:
            Diccionario con estadísticas de la recolección.
        """
        stats = {
            "issues_found": 0,
            "articles_new": 0,
            "downloads_success": 0,
            "errors": 0
        }
        save_interval = 5

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.main_url, wait_until="load", timeout=30000)
                await asyncio.sleep(1)

                # Obtener enlaces a números
                issue_links = await page.query_selector_all("h4 a")
                issue_urls = [await link.get_attribute("href") for link in issue_links]
                stats["issues_found"] = len(issue_urls)

                self.logger.info(f"[Archivo] {len(issue_urls)} números encontrados")

                for issue_url in issue_urls:
                    if not issue_url:
                        continue

                    try:
                        await page.goto(issue_url, wait_until="load", timeout=30000)
                        self.logger.info(f"[Número] Procesando {issue_url}")

                        # Obtener enlace al artículo/número
                        article_link = await self.safe_attr(page, "div#issueCoverImage a", "href")
                        if not article_link:
                            continue

                        await page.goto(article_link, timeout=30000)

                        # Obtener título
                        title = await self.safe_inner_text(page, "h2")
                        item_id = f"Otarq_{title[:50]}"

                        if item_id in self.existing_ids:
                            self.logger.debug(f"[Skip] {item_id} ya existe")
                            continue

                        # Obtener enlace al PDF viewer
                        pdf_viewer_link = await self.safe_attr(page, "td.tocGalleys a", "href")
                        if not pdf_viewer_link:
                            continue

                        await page.goto(pdf_viewer_link, timeout=30000)

                        # Obtener enlace directo al PDF
                        pdf_url = await self.safe_attr(page, "p a.action", "href")
                        if not pdf_url:
                            continue

                        # Descargar PDF
                        pdf_path = await self.download_pdf(item_id, pdf_url)
                        stats["downloads_success"] += 1

                        # Registrar
                        self.append_record({
                            "id": item_id,
                            "title": title,
                            "issue_url": issue_url,
                            "pdf_url": pdf_url,
                            "pdf_path": pdf_path
                        })

                        self.existing_ids.add(item_id)
                        stats["articles_new"] += 1

                        if len(self.records_buffer) >= save_interval:
                            self.save_to_parquet()

                    except Exception as e:
                        self.logger.error(f"[Error] {issue_url}: {e}")
                        stats["errors"] += 1
                        await asyncio.sleep(2)

            except Exception as e:
                self.logger.error(f"[Error] Principal: {e}")
                stats["errors"] += 1
            finally:
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE REVISTA OTARQ")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.collect_articles())

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Números encontrados: {stats['issues_found']}")
        self.logger.info(f"  Artículos nuevos: {stats['articles_new']}")
        self.logger.info(f"  Descargas exitosas: {stats['downloads_success']}")
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
        folders=["ALIA", "Revista_Otarq"]
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

        # Análisis de valores nulos
        print(f"\n📋 ANÁLISIS DE VALORES NULOS:")
        print("-" * 60)
        for col in df.columns:
            null_count = df.filter(pl.col(col).is_null()).height
            pct = (null_count / len(df)) * 100 if len(df) > 0 else 0
            print(f"   {col:15s}: {null_count:6d} nulos ({pct:5.1f}%)")

        # Análisis de duplicados
        print(f"\n🔄 ANÁLISIS DE DUPLICADOS:")
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
