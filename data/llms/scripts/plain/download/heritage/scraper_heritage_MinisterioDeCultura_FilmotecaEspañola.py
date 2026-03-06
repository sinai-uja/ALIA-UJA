"""Recolector de datos web para la Filmoteca Española del Ministerio de Cultura.

Este módulo implementa un método que recolecta información sobre obras
audiovisuales del catálogo de la Filmoteca Española (RAFI) mediante
Playwright. Los datos se extraen navegando por el catálogo de obras
audiovisuales, registro a registro, y descargando las imágenes asociadas.

El catálogo de la Filmoteca Española contiene:
    - Obras audiovisuales históricas y contemporáneas
    - Películas, cortometrajes y documentales del patrimonio fílmico español
    - Registros con sinopsis, géneros y descripciones físicas

Example:
    Ejecución básica::

        python scraper_heritage_MinisterioDeCultura_FilmotecaEspañola.py

    Esto navegará por el catálogo de obras audiovisuales, extraerá los
    metadatos de cada ficha y descargará las imágenes de portada.

Note:
    Los datos son de acceso público a través del catálogo RAFI del
    Ministerio de Cultura.
    URL: https://catalogos.cultura.gob.es/RAFI
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
import re


def sanitize_filename(filename: str) -> str:
    """Limpia una cadena para que sea un nombre válido para un archivo.

    Reemplaza o elimina caracteres inválidos comunes en Windows, macOS y
    Linux, y evita nombres reservados del sistema operativo Windows.

    Args:
        filename: Nombre original del archivo.

    Returns:
        Nombre seguro para usar en rutas de archivos.
    """
    # Define caracteres inválidos comunes (Windows especialmente)
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
    # Reemplaza caracteres inválidos por guion bajo
    sanitized = re.sub(invalid_chars, '_', filename)

    # Elimina espacios al inicio y final
    sanitized = sanitized.strip()

    # Evita nombres reservados de Windows (como CON, PRN, AUX...)
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    name_upper = sanitized.upper().split('.')[0]
    if name_upper in reserved_names:
        sanitized = "_" + sanitized

    return sanitized


class Scraper:
    """Recolector de datos web con Playwright para la Filmoteca Española.

    Esta clase gestiona el proceso completo de recolección de datos desde
    el catálogo RAFI del Ministerio de Cultura, navegando por las fichas
    de obras audiovisuales y descargando sus imágenes de portada.

    Attributes:
        dataset_folder: Ruta a la carpeta raíz del dataset.
        img_folder: Ruta a la subcarpeta de imágenes descargadas.
        csv_path: Ruta al archivo CSV de salida.
        logger: Logger configurado para el recolector.
        urls: URL de la página de búsqueda principal del catálogo RAFI.

    Example:
        >>> scraper = Scraper(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Patrimonio_Filmoteca_Española"],
        ...     urls="https://catalogos.cultura.gob.es/RAFI/cgi-rafi/abnetopac/..."
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
                del dataset (ej: ['ALIA', 'Patrimonio_Filmoteca_Española']).
            urls: URL de la página de búsqueda principal del catálogo RAFI.

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

        # Subcarpeta para imágenes de portada
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

        Lanza la navegación asíncrona por el catálogo y, al finalizar,
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

    #TODO: cambiar todo el proceso
    async def extract_info(self, page) -> None:
        """Extrae los metadatos de una ficha de obra audiovisual del catálogo.

        Lee los campos estructurados de la ficha (título, descripción física,
        notas, longitud, género y sinopsis), descarga la imagen de portada
        y persiste el registro en el CSV.

        Args:
            page: Instancia de ``Page`` de Playwright con la ficha de la obra
                ya cargada.
        """
        async with async_playwright() as p:
            try:
                # Extraer el título de la obra
                title = sanitize_filename(await self.safe_text_content(page, 'div.auth:has-text("Título:") + div.titn'))

                # Extraer la descripción física
                description = await self.safe_text_content(page, 'div.auth:has-text("Descripción física:") + div.titn')

                # Extraer las notas
                notes = await self.safe_text_content(page, 'div.auth:has-text("Notas:") + div.titn')

                # Extraer la longitud
                length = await self.safe_text_content(page, 'div.auth:has-text("Longitud") + div.titn')

                # Extraer el género
                genre = await self.safe_text_content(page, 'div.auth:has-text("Género:") + div.titn')

                # Extraer la sinopsis
                synopsis = await self.safe_text_content(page, 'div.auth:has-text("Sinopsis:") + div.titn')

                # Descargar la imagen de portada de la obra
                img_url = await page.get_attribute('.coverDoc img', 'src')
                img_url = "https://catalogos.cultura.gob.es" + img_url
                await self.download_image(title, img_url)

                # Construir y persistir el registro
                record_data = {
                    "id": title,
                    "url": page.url,
                    "desciption": description,
                    "notes": notes,
                    "length": length,
                    "genre": genre,
                    "synopsis": synopsis,
                    "img_url": img_url or "",
                    "text": f"{title}\n{description}\n{notes}\n{length}\n{genre}\n{synopsis}"
                }

                self.append_record(record_data)

            except Exception as e:
                self.logger.error(f"Error al explorar enlace")

    async def nav_catalog(self, url: str) -> None:
        """Navega por el catálogo de obras audiovisuales y procesa cada ficha.

        Accede al catálogo RAFI, filtra por obras audiovisuales, inicia
        la búsqueda general y recorre todos los registros uno a uno hasta
        que no haya más páginas disponibles.

        Args:
            url: URL de la página de búsqueda principal del catálogo RAFI.

        Raises:
            Exception: Si se produce un error de navegación general.
        """
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()
                await page.goto(url, timeout=100000)

                # Conectar al sistema de catálogo
                await page.click("a.ex_lnk:has-text('conectar')")

                # Filtrar por obras audiovisuales
                await page.click('a:has(img[alt="Obras audiovisuales"])')

                # Hacer búsqueda general (todos los registros)
                await page.fill("#xsqf01", "*")
                await page.click("a.butt_send:has-text('Buscar')")

                # Entrar en el primer resultado y recorrer todos
                await page.click("strong ~ a")
                await page.wait_for_load_state("networkidle")
                while True:
                    await self.extract_info(page)

                    # Intentamos ir a la siguiente página
                    if not await self.next_page(page):
                        break

                    self.logger.info(f"[NEXT_PAGE] ...")

            except Exception as e:
                self.logger.error(f"Error al explorar enlace")
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def next_page(self, page: Page) -> bool:
        """Navega a la siguiente ficha de resultados si está disponible.

        Busca el botón «Siguiente» en la página actual y, si está visible,
        hace clic en él y espera a que la nueva ficha cargue.

        Args:
            page: Objeto ``Page`` de Playwright con la ficha actual cargada.

        Returns:
            ``True`` si se ha navegado correctamente a la siguiente ficha,
            ``False`` si no existe botón siguiente o no está visible.
        """
        # Buscar el botón «Siguiente»
        next_button = await page.query_selector('a.noacti[title="Siguiente"]')

        if next_button:
            # El botón existe, verificar si está visible
            if await next_button.is_visible():
                await next_button.click()
                await page.wait_for_load_state("networkidle")
                return True
            # No hay botón siguiente visible, terminamos
            else:
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
        folders=["ALIA", "Patrimonio_Filmoteca_Española"],
        urls="https://catalogos.cultura.gob.es/RAFI/cgi-rafi/abnetopac/O14016/ID1869945a/NT1?ACC=120&FORM=6"
    )

    # Ejecutar proceso de recolección
    scraper.execute()