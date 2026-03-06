"""Recolector de datos web para la Guía Digital del Patrimonio de Andalucía.

Este módulo implementa un método que recolecta información sobre bienes
patrimoniales de la Guía Digital del Patrimonio Cultural de Andalucía
(IAPH). Los datos se extraen mediante la API de búsqueda y descargando
los PDFs de fichas de cada bien.

Dominios disponibles:
    - paisaje: Paisajes culturales de Andalucía
    - inmaterial: Patrimonio cultural inmaterial
    - inmueble: Bienes inmuebles protegidos
    - mueble: Bienes muebles catalogados

Example:
    Ejecución básica::

        python scraper_heritage_guia_digital_patrimonio_andalucia.py

    Esto procesará todos los dominios, descargando fichas PDF
    y generando archivos Parquet por dominio.

Attributes:
    DOMAINS (dict): Configuración de cada dominio con headers y columnas.
    SEARCH_URL (str): Template de URL para la API de búsqueda.
    BATCH_SIZE (int): Tamaño de lote para paginación de la API.

Note:
    Los datos son de acceso público a través del portal del IAPH.
    URL: https://guiadigital.iaph.es
"""

import asyncio
import json
import logging
import os
import re

import aiohttp
import polars as pl
import win32net
import yaml
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from tqdm.asyncio import tqdm_asyncio


# Configuración de dominios
DOMAINS = {
    "paisaje": {
        "n_items": 117,
        "columns": [
            "id", "url", "denominacion", "provincia",
            "demarcacion_paisajistica", "area", "ambito",
            "descripcion", "pdf_path"
        ],
    },
    "inmaterial": {
        "n_items": 2000,
        "columns": [
            "id", "url", "codigo", "denominacion", "ambito_tematico", 
            "tipologias_actividad", "provincia", "comarca", "municipio", 
            "fecha", "periodicidad", "descripcion", "fuentes", "pdf_path"
        ],
        "field_mapping": [
            ("Código", "codigo"),
            ("Denominación", "denominacion"),
            ("Ámbito Temático", "ambito_tematico"),
            ("Tipologías/Actividad", "tipologias_actividad"),
            ("Provincia", "provincia"),
            ("Comarca", "comarca"),
            ("Municipio", "municipio"),
            ("Fecha", "fecha"),
            ("Periodicidad", "periodicidad"),
            ("DESCRIPCIÓN", "descripcion"),
            ("FUENTES DE INFORMACIÓN", "fuentes"),
        ],
    },
    "inmueble": {
        "n_items": 30000,
        "columns": [
            "id", "url", "denominacion", "codigo", "caracterizacion", 
            "provincia", "municipio", "descripcion", "fuentes", "pdf_path"
        ],
        "field_mapping": [
            ("Denominación", "denominacion"),
            ("Código", "codigo"),
            ("Caracterización", "caracterizacion"),
            ("Provincia", "provincia"),
            ("Municipio", "municipio"),
            ("DESCRIPCIÓN", "descripcion"),
            ("FUENTES DE INFORMACIÓN", "fuentes"),
        ],
    },
    "mueble": {
        "n_items": 110000,
        "columns": [
            "id", "url", "denominacion", "codigo", "provincia", "municipio", 
            "inmueble", "tipologia", "escuelas", "periodos_historicos", 
            "estilos", "cronologia", "iconografias", "autores", "descripcion", 
            "materiales", "tecnicas", "medidas", "proteccion", "fuentes", "pdf_path"
        ],
        "field_mapping": [
            ("Denominación", "denominacion"),
            ("Código", "codigo"),
            ("Provincia", "provincia"),
            ("Municipio", "municipio"),
            ("Inmueble", "inmueble"),
            ("Tipología(s)", "tipologia"),
            ("Escuela(s)", "escuelas"),
            ("P.Histórico(s)", "periodos_historicos"),
            ("Estilo(s)", "estilos"),
            ("Cronología", "cronologia"),
            ("Iconografía(s)", "iconografias"),
            ("Autor(es)", "autores"),
            ("Descripción", "descripcion"),
            ("Material(es)", "materiales"),
            ("Técnica(s)", "tecnicas"),
            ("Medidas", "medidas"),
            ("PROTECCIÓN", "proteccion"),
            ("FUENTES DE INFORMACIÓN", "fuentes"),
        ],
    }
}

# URL template para la API de búsqueda
SEARCH_URL = (
    "https://guiadigital.iaph.es/api/1.0/busqueda/{domain}/q=*:*"
    "&facet.field=provincia_smv&facet=on&facet.mincount=1"
    "&sort=imagen.id_img_smv%20asc&facet.field=comarca_smv"
    "&facet.field=municipio_smv&facet.field=proteccion_s"
    "&facet.field=identifica.ambito_s&facet.field=tipologia.den_tipologia_smv"
)

BATCH_SIZE = 5000
SLEEP_TIME = 1


class DataCollector:
    """Recolector de datos web para la Guía Digital del Patrimonio IAPH.

    Esta clase gestiona la conexión con la API del IAPH, descarga
    las fichas PDF de los bienes patrimoniales y extrae los metadatos.

    Attributes:
        domain: Dominio a procesar (paisaje, inmaterial, inmueble, mueble).
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs descargados.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        api_token: Token de autenticación para la API.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Guia_Digital_Patrimonio_Andalucia"],
        ...     domain="inmueble"
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str],
        domain: str
    ) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red y token de API.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset.
            domain: Dominio a procesar (paisaje, inmaterial, inmueble, mueble).

        Raises:
            ValueError: Si el dominio no es válido.
            RuntimeError: Si no se puede cargar el archivo de configuración.
        """
        if domain not in DOMAINS:
            raise ValueError(
                f"Dominio '{domain}' no válido. Debe ser uno de: {list(DOMAINS.keys())}"
            )

        self.domain = domain
        self.n_items = DOMAINS[domain]["n_items"]

        # Cargar configuración
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)

        # Token de API (desde config o variable de entorno)
        self.api_token = config.get('gdpa_token', os.environ.get('GDPA_API_TOKEN', ''))

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

        # Carpeta para PDFs del dominio
        self.pdf_folder = os.path.join(self.dataset_folder, domain)
        os.makedirs(self.pdf_folder, exist_ok=True)

        # Rutas de archivos
        self.parquet_path = os.path.join(self.dataset_folder, f"{domain}.parquet")
        self.ids_cache_path = os.path.join(self.dataset_folder, f"{domain}_ids.json")

        # Buffer de registros
        self.records_buffer: list[dict] = []

        # Logger
        self.logger = self.setup_logger()

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Domain: {domain}")
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

    async def download_ids_from_api(self) -> list[str]:
        """Descarga la lista de IDs desde la API de búsqueda.

        Usa paginación para obtener todos los IDs del dominio.
        Los IDs se cachean en disco para evitar re-descargas.

        Returns:
            Lista de IDs de los bienes del dominio.
        """
        # Intentar cargar desde caché
        if os.path.exists(self.ids_cache_path):
            self.logger.info(f"Cargando IDs desde caché: {self.ids_cache_path}")
            with open(self.ids_cache_path, "r", encoding="utf-8") as f:
                try:
                    all_results = json.load(f)
                    return [item.get("id", "") for item in all_results]
                except json.JSONDecodeError:
                    self.logger.warning("Error en caché, descargando de nuevo...")

        all_results = []
        url_template = SEARCH_URL.format(domain=self.domain)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                extra_http_headers={"Authorization": f"Bearer {self.api_token}"}
            )
            page = await context.new_page()

            for start in range(0, self.n_items, BATCH_SIZE):
                url = f"{url_template}&start={start}&rows={BATCH_SIZE}"
                self.logger.info(f"[API] Descargando lote {start}...")

                try:
                    await page.goto(url, timeout=60000)
                    html_content = await page.content()

                    soup = BeautifulSoup(html_content, "html.parser")
                    pre_tag = soup.find("pre")

                    if pre_tag:
                        json_data = json.loads(pre_tag.text)
                        docs = json_data.get("response", {}).get("docs", [])
                        all_results.extend(docs)
                        self.logger.info(
                            f"[API] Lote procesado. Total acumulado: {len(all_results)}"
                        )
                except Exception as e:
                    self.logger.error(f"[API] Error en lote {start}: {e}")

            await browser.close()

        # Guardar caché
        with open(self.ids_cache_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

        self.logger.info(f"[API] Total IDs descargados: {len(all_results)}")
        return [item.get("id", "") for item in all_results]

    async def download_pdf_file(self, pdf_url: str, output_path: str) -> bool:
        """Descarga un archivo PDF desde una URL.

        Args:
            pdf_url: URL del archivo PDF.
            output_path: Ruta de destino para el PDF.

        Returns:
            True si la descarga fue exitosa, False en caso contrario.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(pdf_url, timeout=30) as response:
                    if response.status == 200:
                        with open(output_path, "wb") as f:
                            f.write(await response.read())
                        return True
                    else:
                        self.logger.warning(
                            f"[PDF] Status {response.status} para {pdf_url}"
                        )
                        return False
        except Exception as e:
            self.logger.error(f"[PDF] Error descargando {pdf_url}: {e}")
            return False

    def extract_fields_from_text(self, text: str) -> dict:
        """Extrae campos estructurados del texto del PDF.

        Busca las etiquetas definidas en el mapping del dominio
        y extrae los valores correspondientes.

        Args:
            text: Texto extraído del PDF.

        Returns:
            Diccionario con los campos extraídos.
        """
        field_mapping = DOMAINS[self.domain].get("field_mapping", [])
        if not field_mapping:
            return {}

        # Detectar etiquetas presentes y sus posiciones
        present = []
        for label, key in field_mapping:
            match = re.search(rf"{re.escape(label)}\s*:?", text, re.IGNORECASE)
            if match:
                present.append((label, key, match.start()))

        # Ordenar por posición
        present.sort(key=lambda x: x[2])
        present.append(("END", None, len(text)))

        # Extraer valores
        result = {}
        for i, (label, key, start) in enumerate(present[:-1]):
            _, _, end = present[i + 1]
            chunk = text[start:end]
            value = re.sub(rf"^{re.escape(label)}\s*:?\s*", "", chunk, flags=re.IGNORECASE)
            result[key] = value.strip()

        return result

    def extract_paisaje_fields(self, text: str) -> dict:
        """Extrae campos específicos del dominio Paisaje.

        Args:
            text: Texto extraído del PDF.

        Returns:
            Diccionario con los campos del paisaje.
        """
        result = {
            "denominacion": "",
            "provincia": "",
            "demarcacion_paisajistica": "",
            "area": "",
            "ambito": "",
            "descripcion": ""
        }

        # Denominación y Provincia
        match_title = re.match(r"^(.*?)\s*\(([^)]+)\)", text)
        if match_title:
            result["denominacion"] = match_title.group(1).strip()
            result["provincia"] = match_title.group(2).strip()

        # Demarcación Paisajística
        match = re.search(r"Demarcación Paisajística\s*:\s*([^\.\n]+)", text)
        if match:
            result["demarcacion_paisajistica"] = match.group(1).strip()

        # Área
        match = re.search(r"Áreas?\s*:\s*([^\.\n]+)", text)
        if match:
            result["area"] = match.group(1).strip()

        # Ámbito
        match = re.search(r"Ámbitos?/s?\s*:\s*([^\.\n]+)", text)
        if match:
            result["ambito"] = match.group(1).strip()

        # Descripción (resto del texto limpio)
        cleaned = text
        cleaned = re.sub(r"^(.*?)\s*\(([^)]+)\)", '', cleaned, count=1)
        cleaned = re.sub(r"Demarcación Paisajística\s*:\s*[^\.\n]+\.*\s*", '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"Áreas?\s*:\s*[^\.\n]+\.*\s*", '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"Ámbitos?/s?\s*:\s*[^\.\n]+\.*\s*", '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"Correspondencias con el Mapa de Paisajes.*?\.\s*", '', cleaned, flags=re.IGNORECASE)
        result["descripcion"] = cleaned.strip()

        return result

    async def process_item(self, item_id: str) -> bool:
        """Procesa un bien individual descargando su ficha PDF.

        Args:
            item_id: ID del bien a procesar.

        Returns:
            True si el procesamiento fue exitoso.
        """
        pdf_filename = f"ficha-{self.domain}-{item_id}"

        if pdf_filename in self.existing_ids:
            self.logger.debug(f"[Skip] {pdf_filename} ya existe")
            return False

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                url = f'https://guiadigital.iaph.es/bien/{self.domain}/{item_id}'
                await page.goto(url, timeout=30000)
                await asyncio.sleep(SLEEP_TIME)

                # Buscar botón de descarga PDF
                await page.wait_for_selector("text=Descargar PDF", timeout=10000)
                download_button = page.locator("text=Descargar PDF")

                if await download_button.count() > 0:
                    async with page.expect_download(timeout=30000) as download_info:
                        await download_button.first.click(force=True)
                        await asyncio.sleep(SLEEP_TIME)

                    download = await download_info.value
                    pdf_path = os.path.join(self.pdf_folder, f"{pdf_filename}.pdf")
                    await download.save_as(pdf_path)

                    # Añadir registro con metadatos
                    self.append_record({
                        "id": pdf_filename,
                        "url": url,
                        "pdf_path": pdf_path
                    })

                    self.existing_ids.add(pdf_filename)
                    self.logger.info(f"[OK] {pdf_filename} descargado")
                    return True

            except PlaywrightTimeout:
                self.logger.warning(f"[Timeout] {item_id}")
            except Exception as e:
                self.logger.error(f"[Error] {item_id}: {e}")
            finally:
                await browser.close()

        return False

    async def process_paisaje_domain(self) -> int:
        """Procesa el dominio Paisaje usando navegación especial.

        El dominio paisaje requiere navegación diferente a través
        de la búsqueda avanzada.

        Returns:
            Número de fichas nuevas procesadas.
        """
        new_count = 0
        save_interval = 20

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # Requiere headless=False
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                self.logger.info("[Paisaje] Accediendo a la página de inicio...")
                await page.goto("https://guiadigital.iaph.es/inicio")
                await page.wait_for_load_state("networkidle")

                # Búsqueda avanzada
                self.logger.info("[Paisaje] Navegando a búsqueda avanzada...")
                await page.locator("div.circle:has-text('BÚSQUEDA')").nth(0).click()
                await asyncio.sleep(SLEEP_TIME)

                # Seleccionar Paisaje Cultural
                dropdown = page.locator("ng-select:has-text('Seleccionar Tipo Patrimonio')")
                await dropdown.click()
                await asyncio.sleep(SLEEP_TIME)

                await page.locator("li.ng-star-inserted:has-text('Paisaje Cultural')").click()
                await asyncio.sleep(SLEEP_TIME)

                await page.locator("button:has-text('Buscar')").click()
                await page.wait_for_selector("a[href$='.pdf']", timeout=20000)
                await asyncio.sleep(SLEEP_TIME)

                current_page = 1

                while True:
                    self.logger.info(f"[Paisaje] Procesando página {current_page}...")
                    pdf_links = await page.query_selector_all("a[href$='.pdf']")

                    for link in pdf_links:
                        try:
                            async with context.expect_page() as new_page_info:
                                await link.click()

                            new_tab = await new_page_info.value
                            await new_tab.wait_for_load_state("load")

                            pdf_url = new_tab.url
                            item_id = pdf_url.rstrip("/").split("/")[-3]
                            pdf_filename = f"ficha-{self.domain}-{item_id}"

                            if pdf_filename not in self.existing_ids:
                                pdf_path = os.path.join(self.pdf_folder, f"{pdf_filename}.pdf")
                                success = await self.download_pdf_file(pdf_url, pdf_path)

                                if success:
                                    self.append_record({
                                        "id": pdf_filename,
                                        "url": pdf_url,
                                        "pdf_path": pdf_path
                                    })
                                    self.existing_ids.add(pdf_filename)
                                    new_count += 1

                                    if len(self.records_buffer) >= save_interval:
                                        self.save_to_parquet()

                            await new_tab.close()
                            await asyncio.sleep(SLEEP_TIME)

                        except Exception as e:
                            self.logger.error(f"[Paisaje] Error: {e}")

                    # Paginación
                    current_page += 1
                    next_button = page.locator(f"a.ui-paginator-page:has-text('{current_page}')")

                    if await next_button.count() > 0:
                        await next_button.first.scroll_into_view_if_needed()
                        await next_button.first.click()
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(SLEEP_TIME)
                    else:
                        break

            except Exception as e:
                self.logger.error(f"[Paisaje] Error general: {e}")
            finally:
                await browser.close()

        return new_count

    async def execute_async(self) -> None:
        """Ejecuta el proceso de recolección de forma asíncrona.

        Para el dominio paisaje usa navegación especial.
        Para otros dominios, primero descarga IDs y luego procesa.
        """
        self.logger.info("=" * 60)
        self.logger.info(f"INICIANDO RECOLECCIÓN - DOMINIO: {self.domain.upper()}")
        self.logger.info("=" * 60)

        if self.domain == "paisaje":
            new_count = await self.process_paisaje_domain()
        else:
            # Descargar lista de IDs
            item_ids = await self.download_ids_from_api()
            self.logger.info(f"[{self.domain}] Total IDs: {len(item_ids)}")

            # Procesar con concurrencia limitada
            sem = asyncio.Semaphore(8)
            new_count = 0
            save_interval = 50

            async def bounded_process(item_id):
                async with sem:
                    return await self.process_item(item_id)

            tasks = [bounded_process(item_id) for item_id in item_ids]

            for completed in tqdm_asyncio.as_completed(tasks, total=len(tasks)):
                result = await completed
                if result:
                    new_count += 1
                    if len(self.records_buffer) >= save_interval:
                        self.save_to_parquet()

        # Guardar registros pendientes
        if self.records_buffer:
            self.save_to_parquet()

        # Resumen
        self.logger.info("=" * 60)
        self.logger.info("RESUMEN DE RECOLECCIÓN")
        self.logger.info("=" * 60)
        self.logger.info(f"  Dominio: {self.domain}")
        self.logger.info(f"  Fichas nuevas: {new_count}")
        self.logger.info("=" * 60)

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos."""
        asyncio.run(self.execute_async())

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger(f"DataCollector.{self.domain}")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(self.dataset_folder, f"{self.domain}.log"),
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
    # Procesar todos los dominios
    for domain in DOMAINS.keys():
        collector = DataCollector(
            config_path="config.yaml",
            folders=["ALIA", "Guia_Digital_Patrimonio_Andalucia"],
            domain=domain
        )
        collector.execute()

    # =========================================================================
    # ANÁLISIS EXPLORATORIO DEL DATASET
    # =========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    base_folder = None
    for domain in DOMAINS.keys():
        collector = DataCollector(
            config_path="config.yaml",
            folders=["ALIA", "Guia_Digital_Patrimonio_Andalucia"],
            domain=domain
        )
        base_folder = collector.dataset_folder

        if os.path.exists(collector.parquet_path):
            df = pl.read_parquet(collector.parquet_path)

            print(f"\n📊 DOMINIO: {domain.upper()}")
            print(f"   Total de registros: {len(df)}")
            print(f"   Columnas: {df.columns}")

            # Análisis de duplicados
            id_duplicates = len(df) - df.select('id').n_unique()
            print(f"   IDs duplicados: {id_duplicates}")
        else:
            print(f"\n📊 DOMINIO: {domain.upper()} - Sin datos")

    print("\n" + "=" * 80)
