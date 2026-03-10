"""Recolector de datos web para Bienes Culturales de Castilla-La Mancha.

Este módulo implementa un método que recolecta información sobre bienes
culturales del catálogo de patrimonio de Castilla-La Mancha mediante
Playwright. Los datos se extraen de fichas individuales de bienes culturales
y se almacenan en formato Parquet.

El catálogo contiene información sobre:
    - Bienes de Interés Cultural (BIC)
    - Patrimonio arquitectónico
    - Conjuntos históricos
    - Monumentos y sitios históricos

Example:
    Ejecución básica::

        python scraper_heritage_bienes_culturales_castilla_la_mancha.py

    Esto navegará por todas las páginas del catálogo, extraerá la
    información de cada bien cultural y generará un archivo Parquet.

Attributes:
    BASE_URL (str): URL base del catálogo con paginación.
    TOTAL_PAGES (int): Número total de páginas a recorrer.

Note:
    Los datos son de acceso público a través del portal de cultura
    de la Junta de Castilla-La Mancha.
    URL: https://cultura.castillalamancha.es/patrimonio/catalogo-patrimonio-cultural
"""

import asyncio
import logging
import os
from urllib.parse import urljoin

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# URL base del catálogo con paginación
BASE_URL = (
    "https://cultura.castillalamancha.es/patrimonio/catalogo-patrimonio-cultural"
    "?title=&term_node_tid_depth=All&field_bic_categoria_target_id=All"
    "&field_bic_figura_target_id=All&field_bic_tipo_target_id=All&page={page}"
)
TOTAL_PAGES = 58


class DataCollector:
    """Recolector de datos web con Playwright para bienes culturales.

    Esta clase gestiona el proceso completo de recolección de datos desde
    el catálogo de patrimonio cultural de Castilla-La Mancha, navegando
    por cada página del catálogo y extrayendo información de cada ficha.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        url: URL base del catálogo con placeholder para paginación.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Bienes_Culturales_Castilla_LaMancha"],
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
                del dataset (ej: ['ALIA', 'Bienes_Culturales_Castilla_LaMancha']).
            url: URL base del catálogo con placeholder {page} para paginación.

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

        # Rutas de archivos
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # Buffer de registros
        self.records_buffer: list[dict] = []

        # Logger
        self.logger = self.setup_logger()

        # URL base
        self.url = url

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet.

        Carga el archivo Parquet y extrae la columna 'id' para crear
        un conjunto de identificadores. Se usa para evitar duplicados
        durante la recolección.

        Args:
            parquet_path: Ruta al archivo Parquet. Si es None, usa
                self.parquet_path.

        Returns:
            Conjunto (set) con los IDs existentes. Retorna conjunto
            vacío si el archivo no existe o hay error de lectura.
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

        El registro se almacena temporalmente hasta que se llame a
        ``save_to_parquet()`` para persistir los datos.

        Args:
            record_data: Diccionario con los campos del registro. Debe
                contener al menos la clave 'id' como identificador único.
        """
        self.records_buffer.append(record_data)

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

                # Unificar tipos de columnas para evitar incompatibilidades
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
                f"No se pudo escribir en el archivo Parquet {self.parquet_path}: {e}"
            )

    async def extract_item_info(self, page, item_url: str, page_num: int, item_num: int) -> None:
        """Extrae información de una ficha individual de bien cultural.

        Navega a la página de detalle del bien cultural y extrae
        el título y la descripción del contenido.

        Args:
            page: Página de Playwright activa.
            item_url: URL de la ficha del bien cultural.
            page_num: Número de página del catálogo (para generar ID).
            item_num: Número de ítem dentro de la página (para generar ID).
        """
        item_id = f"Bien_Cultural_Castilla_LaMancha_{page_num}_{item_num}"

        # Saltar si ya existe
        if item_id in self.existing_ids:
            self.logger.debug(f"[Skip] {item_id} ya existe")
            return

        try:
            await page.goto(item_url, wait_until="load", timeout=30000)

            # Extraer título
            title_elem = await page.query_selector("h1")
            title = await title_elem.inner_text() if title_elem else ""

            # Extraer texto descriptivo
            paragraphs = await page.query_selector_all("div.container.encabezado-bic p")
            text_parts = []
            for p in paragraphs:
                text = await p.inner_text()
                if text:
                    text_parts.append(text)

            description = " ".join(text_parts)
            full_text = f"{title} {description}".strip()

            # Añadir al buffer
            self.append_record({
                "id": item_id,
                "title": title,
                "url": item_url,
                "text": full_text
            })

            # Marcar como existente para evitar duplicados en esta ejecución
            self.existing_ids.add(item_id)

            self.logger.info(f"[Extraído] {item_id}: {title[:50]}...")

        except PlaywrightTimeout:
            self.logger.warning(f"[Timeout] {item_url}")
        except Exception as e:
            self.logger.error(f"[Error] {item_url}: {e}")

    async def collect_catalog(self) -> dict:
        """Recorre el catálogo completo y extrae información de cada bien.

        Navega por todas las páginas del catálogo, obtiene los enlaces
        a las fichas individuales y extrae la información de cada una.
        Guarda incrementalmente cada 50 registros.

        Returns:
            Diccionario con estadísticas de la recolección.
        """
        stats = {
            "pages_processed": 0,
            "items_found": 0,
            "items_new": 0,
            "errors": 0
        }
        save_interval = 50

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                for page_num in range(TOTAL_PAGES):
                    page_url = self.url.format(page=page_num)
                    self.logger.info(f"[Página {page_num + 1}/{TOTAL_PAGES}] {page_url}")

                    try:
                        await page.goto(page_url, wait_until="load", timeout=30000)

                        # Obtener enlaces a fichas individuales
                        link_elements = await page.query_selector_all("div.field-content a")
                        item_urls = []

                        for link in link_elements:
                            href = await link.get_attribute("href")
                            if href:
                                full_url = urljoin(page_url, href)
                                item_urls.append(full_url)

                        stats["items_found"] += len(item_urls)
                        self.logger.info(f"[Página {page_num + 1}] {len(item_urls)} enlaces encontrados")

                        # Procesar cada ficha
                        for item_num, item_url in enumerate(item_urls):
                            initial_count = len(self.records_buffer)
                            await self.extract_item_info(page, item_url, page_num, item_num)

                            if len(self.records_buffer) > initial_count:
                                stats["items_new"] += 1

                            # Guardar incrementalmente
                            if len(self.records_buffer) >= save_interval:
                                self.save_to_parquet()

                        stats["pages_processed"] += 1

                    except PlaywrightTimeout:
                        self.logger.warning(f"[Timeout] Página {page_num}")
                        stats["errors"] += 1
                    except Exception as e:
                        self.logger.error(f"[Error] Página {page_num}: {e}")
                        stats["errors"] += 1

            finally:
                await page.close()
                await context.close()
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Inicia la recolección de forma asíncrona, navegando por el
        catálogo. Al finalizar, todos los datos quedan guardados
        en el archivo Parquet.
        """
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN DE BIENES CULTURALES CLM")
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
        self.logger.info(f"  Items encontrados: {stats['items_found']}")
        self.logger.info(f"  Items nuevos guardados: {stats['items_new']}")
        self.logger.info(f"  Errores: {stats['errors']}")
        self.logger.info("=" * 60)

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
    # URL del catálogo de patrimonio cultural
    CATALOG_URL = BASE_URL

    # Crear instancia del recolector de datos
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Bienes_Culturales_Castilla_LaMancha"],
        url=CATALOG_URL
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
        print("-" * 60)
        id_duplicates = len(df) - df.select('id').n_unique()
        print(f"   IDs duplicados: {id_duplicates}")

        # Longitud de textos
        print(f"\n📝 LONGITUD DE TEXTOS:")
        print("-" * 60)
        text_lengths = df.select(pl.col("text").str.len_chars().alias("len"))
        if len(text_lengths) > 0:
            print(f"   Mínimo: {text_lengths['len'].min()} caracteres")
            print(f"   Máximo: {text_lengths['len'].max()} caracteres")
            print(f"   Media: {text_lengths['len'].mean():.0f} caracteres")

        # Ejemplos
        print(f"\n📄 EJEMPLOS DE REGISTROS:")
        print("-" * 60)
        for row in df.head(3).iter_rows(named=True):
            title = row['title'][:60] + "..." if len(row['title']) > 60 else row['title']
            print(f"   [{row['id']}] {title}")

        print("\n" + "=" * 80)
    else:
        print("No existe archivo Parquet para analizar.")
