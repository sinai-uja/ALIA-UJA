"""Recolector de datos web para el Catálogo ICAA de Cine Español.

Este módulo implementa un método que recolecta información sobre obras
audiovisuales españolas del Catálogo ICAA (Instituto de la Cinematografía
y de las Artes Audiovisuales) del Ministerio de Cultura mediante Playwright.
Los datos se extraen navegando por el catálogo filtrado por nacionalidad
española y procesando cada ficha de película individualmente.

El catálogo ICAA contiene:
    - Películas, cortometrajes y obras audiovisuales de producción española
    - Metadatos de directores, géneros, sinopsis y calificaciones
    - Expedientes oficiales ICAA de cada producción

Example:
    Ejecución básica::

        python scraper_heritage_MinisterioDeCultura_PatrimonioAudiovisualCineEspañol.py

    Esto navegará por el catálogo ICAA filtrando por España, extraerá los
    metadatos de cada ficha y descargará las imágenes de carátula asociadas.

Note:
    Los datos son de acceso público a través del Catálogo del ICAA del
    Ministerio de Cultura.
    URL: https://sede.mcu.gob.es/CatalogoICAA/
"""


import asyncio
import csv
import logging
import os
from pydoc import synopsis

import aiohttp
import ssl
from omegaconf import OmegaConf
from playwright.async_api import async_playwright, Page
import polars as pl
import win32net


class Scraper:
    """Recolector de datos web con Playwright para el Catálogo ICAA de Cine Español.

    Esta clase gestiona el proceso completo de recolección de datos desde
    el Catálogo ICAA del Ministerio de Cultura, navegando por las fichas
    de obras audiovisuales de producción española y descargando sus
    imágenes de carátula.

    Attributes:
        dataset_folder: Ruta a la carpeta raíz del dataset.
        img_folder: Ruta a la subcarpeta de imágenes descargadas.
        csv_path: Ruta al archivo CSV de salida.
        logger: Logger configurado para el recolector.
        urls: URL de la página de búsqueda principal del catálogo ICAA.

    Example:
        >>> scraper = Scraper(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Patrimonio_Audiovisual_Cine_Español"],
        ...     urls="https://sede.mcu.gob.es/CatalogoICAA/#"
        ... )
        >>> scraper.execute()
    """

    def __init__(self, config_path: str, folders: list[str], urls: dict) -> None:
        """Inicializa el recolector de datos.

        Carga la configuración, monta el disco de red, crea las carpetas
        necesarias y configura el logger.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset (ej: ['ALIA', 'Patrimonio_Audiovisual_Cine_Español']).
            urls: URL de la página de búsqueda principal del catálogo ICAA.

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
            win32net.error: Si falla la conexión al disco de red.
        """
        # Cargar configuración y conectar disco de red
        config = OmegaConf.load(config_path)
        netresource = {
            'remote': config.disk_path,
            'password': config.password,
            'user': config.user
        }
        win32net.NetUseAdd(None, 2, netresource)

        # Crear estructura de carpetas
        self.dataset_folder = os.path.join(config.disk_path, *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        # Subcarpeta para imágenes de carátula
        self.img_folder = os.path.join(self.dataset_folder, "img")
        os.makedirs(self.img_folder, exist_ok=True)

        # Rutas de archivos y configuración
        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.logger = self.setup_logger()
        self.urls = urls

    def append_record(self, record_data: dict) -> None:
        """Añade un nuevo registro al archivo CSV de salida.

        Si el archivo CSV no existe, escribe la cabecera antes de añadir
        la primera fila.

        Args:
            record_data: Diccionario con los campos del registro a guardar.

        Raises:
            IOError: Si no se puede escribir en el archivo CSV.
        """
        try:
            file_exists = os.path.exists(self.csv_path)
            with open(self.csv_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=record_data.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(record_data)
            self.logger.info(f"Registro con ID {record_data['id']} guardado en el CSV.")
        except IOError as e:
            self.logger.error(f"No se pudo escribir en el CSV {self.csv_path}: {e}")

    async def download_image(self, img_id: str, img_url: str) -> None:
        """Descarga una imagen desde una URL y la guarda en la carpeta de imágenes.

        La descarga se realiza de forma asíncrona con ``aiohttp``, omitiendo
        la verificación SSL para evitar errores con certificados del servidor.

        Args:
            img_id: Identificador único utilizado como nombre del archivo
                (sin extensión). El archivo se guardará como ``{img_id}.jpg``.
            img_url: URL de la imagen a descargar.
        """
        img_path = os.path.join(self.img_folder, f"{img_id}.jpg")

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.get(img_url) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    with open(img_path, "wb") as f:
                        f.write(content)
                    self.logger.info(f"Imagen {img_id} descargada correctamente.")

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Lanza la navegación asíncrona por el catálogo ICAA y, al finalizar,
        realiza el postprocesado para generar el Parquet.
        """
        asyncio.run(self.nav_catalog(self.urls))
        self.postprocess()

    async def safe_text_content(self, page, selector: str, timeout: int = 5000) -> str:
        """Extrae el texto de un elemento de la página de forma segura.

        Captura cualquier excepción que pueda producirse al intentar
        localizar el selector, evitando que un elemento ausente detenga
        la ejecución.

        Args:
            page: Instancia de ``Page`` de Playwright usada para la navegación.
            selector: Selector CSS o de texto del elemento a extraer.
            timeout: Tiempo máximo de espera en milisegundos antes de
                desistir en la operación. Por defecto 5000 ms.

        Returns:
            Texto del elemento encontrado, o cadena vacía si el elemento
            no existe o se produce un error.
        """
        try:
            return await page.text_content(selector, timeout=timeout) or ""
        except Exception as e:
            print(f"[WARN] No se pudo extraer texto con selector '{selector}': {e}")
            return ""

    async def safe_eval_on_selector_all(self, page, selector: str, script: str):
        """Evalúa un script JavaScript sobre todos los elementos que coincidan con el selector.

        Captura cualquier excepción que pueda producirse, evitando que
        un selector inválido detenga la ejecución.

        Args:
            page: Instancia de ``Page`` de Playwright usada para la navegación.
            selector: Selector CSS de los elementos sobre los que aplicar el script.
            script: Expresión o función JavaScript a evaluar con los elementos
                seleccionados como argumento.

        Returns:
            Resultado de la evaluación del script, o lista vacía si el selector
            no coincide con ningún elemento o se produce un error.
        """
        try:
            return await page.eval_on_selector_all(selector, script)
        except Exception as e:
            print(f"[WARN] No se pudo evaluar '{selector}': {e}")
            return []

    async def extract_info(self, link: str) -> None:
        """Extrae los metadatos de la ficha de una película del catálogo ICAA.

        Abre una instancia de Playwright, navega a la URL de la ficha en su
        versión en castellano, extrae los campos estructurados (título, directores,
        calificación, año, duración, género y sinopsis en ambos idiomas),
        descarga la imagen de carátula usando el expediente ICAA como
        identificador y persiste el registro en el CSV.

        Args:
            link: URL de la página de la ficha de la película en el catálogo ICAA.

        Raises:
            Exception: Si se produce un error al navegar o extraer datos de la ficha.
        """
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()

                # Redirigir a la versión en castellano de la ficha
                link_es = link.replace("/CatalogoICAA/", "/CatalogoICAA/es-es/")
                await page.goto(link_es, timeout=10000)

                # Extraer el título de la película
                title = await self.safe_text_content(page, "h2.custom-detail-title")

                # Extraer los directores
                directors = await self.safe_eval_on_selector_all(page,
                    "a.director-detail-big",
                    "els => els.map(e => e.textContent.trim())"
                )
                directors_str = ", ".join(directors)

                # Extraer la calificación
                rating = await self.safe_text_content(page, "label:has-text('Calificación:') + label")

                # Extraer el año de producción
                year = await self.safe_text_content(page, "label:has-text('Año de Producción:') + label")

                # Extraer la duración
                duration = await self.safe_text_content(page, "label:has-text('Duración:') + label")

                # Extraer el género
                genre = await self.safe_text_content(page, "label:has-text('Género:') + label")

                # Extraer la sinopsis en castellano e inglés
                synopsis_spanish = await self.safe_text_content(page, "label:has-text('Sinopsis en Castellano:') + p")
                synopsis_english = await self.safe_text_content(page, "label:has-text('Sinopsis en Inglés:') + p")

                # Extraer el número de expediente ICAA (usado como ID)
                ICAA = await self.safe_text_content(page, "label:has-text('Expediente ICAA:') + label")

                # Descargar la imagen de carátula usando el expediente como nombre
                partial_url = await page.get_attribute("div.pro-img-big.fix > a", "href")
                img_url = None
                if partial_url:
                    img_url = "https://sede.mcu.gob.es/" + partial_url
                    await self.download_image(ICAA, img_url)

                # Construir y persistir el registro
                record_data = {
                    "id": ICAA,
                    "url": link,
                    "title": title,
                    "rating": rating,
                    "directors": directors_str,
                    "year": year,
                    "duration": duration,
                    "genre": genre,
                    "synopsis_spanish": synopsis_spanish,
                    "synopsis_english": synopsis_english,
                    "img_url": img_url or "",
                    "text": f"{title}\n{directors}\n{rating}\n{year}\n{duration}\n{genre}\n{synopsis_spanish}\n{synopsis_english}"
                }

                self.append_record(record_data)

            except Exception as e:
                self.logger.error(f"Error al explorar enlace {link}: {e}")
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def nav_catalog(self, url: str) -> None:
        """Navega por el catálogo ICAA y procesa cada ficha de película.

        Accede al catálogo ICAA, filtra los resultados por nacionalidad
        española (código 100), lanza la búsqueda y recorre todas las páginas
        de resultados procesando cada ficha individualmente hasta que no
        haya más páginas disponibles.

        Args:
            url: URL de la página de búsqueda principal del catálogo ICAA.

        Raises:
            Exception: Si se produce un error de navegación general.
        """
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()
                await page.goto(url, timeout=100000)

                # Esperar a que el filtro de países esté disponible
                await page.wait_for_selector("#filter_p_pais")

                # Seleccionar la nacionalidad española (código 100)
                await page.select_option("#filter_p_pais", value="100")

                # Lanzar la búsqueda
                await page.click("#buttonSearchMovies2")
                await page.wait_for_selector("div.list-pro-details.fix a")

                while True:
                    # Recopilar las URLs de todas las fichas de la página actual
                    item_urls = [await item.get_attribute("href") for item in await page.query_selector_all("div.list-pro-details.fix a.list-pro-title")]
                    data = []
                    for link in item_urls:
                        self.logger.info(f"Clicando en película {"https://sede.mcu.gob.es/" + link}")
                        data.append(await self.extract_info("https://sede.mcu.gob.es/" + link))

                    # Intentar ir a la siguiente página de resultados
                    if not await self.next_page(page):
                        break

                    self.logger.info(f"[NEXT_PAGE] ...")

            except Exception as e:
                self.logger.error(f"Error al explorar enlace {"https://sede.mcu.gob.es/" + url}: {e}")
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def next_page(self, page: Page) -> bool:
        """Navega a la siguiente página de resultados si está disponible.

        Busca el elemento de paginación «Siguiente» en la lista de resultados
        y, si existe y no está deshabilitado, hace clic en él y espera a que
        cargue la nueva página.

        Args:
            page: Objeto ``Page`` de Playwright con la página de resultados
                actual cargada.

        Returns:
            ``True`` si se ha navegado correctamente a la siguiente página,
            ``False`` si el elemento no existe o está deshabilitado.
        """
        # Buscar el elemento de paginación «Siguiente»
        next_li = await page.query_selector("li.PagedList-skipToNext")

        if not next_li:
            # No hay botón siguiente, terminamos
            return False

        li_class = await next_li.get_attribute("class")
        if "disabled" in li_class:
            # Botón deshabilitado, no hay más páginas
            return False

        # Hacer clic en «Siguiente» y esperar a que cargue la página
        next_a = await next_li.query_selector("a")
        if next_a:
            await next_a.click()
            await page.wait_for_load_state("networkidle")
            return True
        return False

    def postprocess(self) -> None:
        """Postprocesa el CSV eliminando duplicados y nulos, y genera el Parquet.

        Lee el CSV de salida, elimina registros sin texto, deduplica por
        contenido de texto e ID, rellena nulos con cadena vacía y escribe
        el resultado en un archivo Parquet.
        """
        df = pl.read_csv(self.csv_path, encoding="utf-8")
        df = df.drop_nulls(subset=["text"])
        df = df.unique(subset=["text"])
        df = df.unique(subset=["id"], keep="first")
        df = df.fill_null("")
        df.write_parquet(os.path.join(self.dataset_folder, "output.parquet"))
        self.logger.info(f"Postprocesado finalizado. Registros únicos con texto: {df.height}")

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Crea un logger con salida simultánea a fichero (en la carpeta del
        dataset) y a la consola, ambos con nivel INFO.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger(os.path.basename(self.dataset_folder))
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(self.dataset_folder, f"{os.path.basename(self.dataset_folder)}.log"), mode='w', encoding='utf-8')
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
    scraper = Scraper(
        config_path="config.yaml",
        folders=["ALIA", "Patrimonio_Audiovisual_Cine_Español"],
        urls="https://sede.mcu.gob.es/CatalogoICAA/#"
    )

    # Ejecutar proceso de recolección
    scraper.execute()