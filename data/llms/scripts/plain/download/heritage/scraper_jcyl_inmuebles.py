"""Recolector de datos web para el Inventario de Bienes Inmuebles de Castilla y León.

Este módulo implementa un método que recolecta información sobre inmuebles
protegidos del patrimonio cultural de Castilla y León desde el servicio
web del Portal de Datos Abiertos de la Junta de Castilla y León (JCYL)
mediante Playwright. Los datos se extraen navegando por los resultados de
búsqueda y accediendo a cada ficha de detalle, descargando y fusionando
los documentos PDF asociados cuando están disponibles.

El catálogo de inmuebles de JCYL contiene:
    - Bienes de Interés Cultural (BIC) de Castilla y León
    - Inmuebles con categoría de protección y ubicación
    - Documentación técnica descargable en formato PDF

Example:
    Ejecución básica::

        python scraper_jcyl_inmuebles.py

    Esto navegará por el buscador de inmuebles, extraerá los metadatos
    de cada ficha y descargará los PDFs asociados.

Note:
    Los datos son de acceso público a través del servicio de búsqueda
    de la Junta de Castilla y León.
    URL: https://servicios.jcyl.es/pweb/buscarInmueble.do
"""

import asyncio
import csv
import logging
import os
import re
import shutil
import time
from typing import Optional, List

import fitz  # PyMuPDF
import polars as pl
import requests
import win32net
from omegaconf import OmegaConf
from playwright.async_api import async_playwright, Page


def sanitize_filename(filename: str) -> str:
    """Limpia una cadena para que sea un nombre válido para un archivo.

    Reemplaza caracteres inválidos por guion bajo y evita nombres reservados
    del sistema operativo Windows.

    Args:
        filename: Nombre original del archivo. Si está vacío, devuelve
            ``'sin_titulo'``.

    Returns:
        Nombre seguro para usar en rutas de archivos.
    """
    if not filename:
        return "sin_titulo"
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
    sanitized = re.sub(invalid_chars, '_', filename)
    sanitized = sanitized.strip()
    # Evitar nombres reservados de Windows
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    name_upper = sanitized.upper().split('.')[0]
    if name_upper in reserved_names:
        sanitized = "_" + sanitized
    return sanitized


class JcylScraper:
    """Recolector de datos web con Playwright para el inventario de inmuebles de la JCYL.

    Esta clase gestiona el proceso completo de recolección de datos del
    inventario de bienes inmuebles protegidos de Castilla y León, navegando
    por los resultados de búsqueda, procesando cada ficha de detalle y
    fusionando los PDFs descargados en un único documento por inmueble.

    Attributes:
        config: Configuración cargada desde el archivo YAML.
        dataset_folder: Ruta a la carpeta raíz del dataset.
        pdf_folder: Ruta a la subcarpeta de PDFs fusionados.
        csv_path: Ruta al archivo CSV de salida.
        logger: Logger configurado para el recolector.
        temp_dir: Carpeta temporal para descargas antes de la fusión.
        processed_ids: Conjunto de IDs ya procesados para evitar duplicados.

    Example:
        >>> scraper = JcylScraper(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Castilla y Leon"]
        ... )
        >>> asyncio.run(scraper.scrape())
    """

    def __init__(self, config_path: str, folders: list[str]) -> None:
        """Inicializa el recolector de datos.

        Carga la configuración, monta el disco de red, crea las carpetas
        necesarias (incluyendo la temporal), configura el logger y carga
        los IDs ya procesados.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset (ej: ['ALIA', 'Castilla y Leon']).

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
        """
        print("[INIT] Iniciando scraper...")
        self.config = OmegaConf.load(config_path)
        print(f"[INIT] Config cargada: {self.config.disk_path}")

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
        print(f"[INIT] Creando directorio: {self.dataset_folder}")
        os.makedirs(self.dataset_folder, exist_ok=True)

        # Subcarpeta para PDFs fusionados
        self.pdf_folder = os.path.join(self.dataset_folder, "pdfs")
        os.makedirs(self.pdf_folder, exist_ok=True)

        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.logger = self.setup_logger()
        self.logger.info("Logger inicializado")

        # Carpeta temporal para descargas antes del merge
        self.temp_dir = os.path.join(self.dataset_folder, "temp_downloads")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.logger.info(f"Scraper inicializado. Dataset: {self.dataset_folder}")

        # Conjunto para rastrear IDs ya procesados
        self.processed_ids = set()
        self._load_processed_ids()

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Crea un logger con salida simultánea a fichero (en la carpeta del
        dataset) y a la consola, ambos con nivel INFO.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger("JcylScraper")
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
        """Inicializa el navegador Playwright y el contexto de navegación.

        Crea instancias de ``playwright``, ``browser`` y ``context``
        como atributos de la clase, con soporte para descargas activado.
        """
        self.logger.info("Iniciando navegador...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(accept_downloads=True)
        self.logger.info("Navegador iniciado")

    def _load_processed_ids(self) -> None:
        """Carga los IDs ya procesados desde el CSV existente.

        Si el CSV de salida existe, lee la columna ``id`` para poblar
        ``self.processed_ids`` y evitar reprocesar registros en ejecuciones
        posteriores.
        """
        if os.path.exists(self.csv_path):
            try:
                df = pl.read_csv(self.csv_path)
                if 'id' in df.columns:
                    self.processed_ids = set(df['id'].to_list())
                    self.logger.info(f"Cargados {len(self.processed_ids)} IDs ya procesados")
            except Exception as e:
                self.logger.warning(f"No se pudo cargar IDs procesados: {e}")

    async def close(self) -> None:
        """Cierra el contexto, el navegador, Playwright y la carpeta temporal.

        Intenta cerrar cada recurso de forma independiente y elimina la
        carpeta temporal de descargas al finalizar.
        """
        try:
            await self.context.close()
        except Exception as e:
            self.logger.warning(f"Error cerrando contexto: {e}")
        try:
            await self.browser.close()
        except Exception as e:
            self.logger.warning(f"Error cerrando navegador: {e}")
        try:
            await self.playwright.stop()
        except Exception as e:
            self.logger.warning(f"Error deteniendo playwright: {e}")
        # Limpiar directorio temporal
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            self.logger.warning(f"No se pudo eliminar carpeta temporal: {e}")

    async def process_detail(self, url: str) -> dict:
        """Procesa la ficha de detalle de un inmueble protegido.

        Abre un contexto efímero, navega a la URL, extrae denominación,
        categoría de protección y ubicación, descarga todos los documentos
        PDF enlazados y los fusiona en un único fichero con PyMuPDF.
        Si no hay PDFs, utiliza la descripción textual como contenido.

        Args:
            url: URL de la página de detalle del inmueble en el servicio JCYL.

        Returns:
            Diccionario con los campos ``id``, ``description``, ``category``,
            ``ubication``, ``text``, ``pdf_path`` y ``url``,
            o diccionario vacío si el inmueble ya existe o si ocurrió un error.
        """
        # Crear un contexto nuevo y limpio para este detalle
        detail_context = await self.browser.new_context(accept_downloads=True)
        page = await detail_context.new_page()

        try:
            self.logger.info(f"Procesando: {url}")
            await page.goto(url, timeout=60000)

            # Extraer datos de labels con clase labelDatosExpe
            labels = await page.query_selector_all('label.labelDatosExpe')

            denominacion = ""
            category = ""
            ubication = ""

            for label in labels:
                text = await label.inner_text()
                text = text.strip()

                if text.startswith("Denominación:"):
                    denominacion = text.replace("Denominación:", "").strip()
                elif text.startswith("Categoría Protección:"):
                    category = text.replace("Categoría Protección:", "").strip()
                elif text.startswith("Ubicación:"):
                    ubication = text.replace("Ubicación:", "").strip()

            if not denominacion:
                title_elem = await page.query_selector('.titulo_entradilla')
                if title_elem:
                    denominacion = await title_elem.inner_text()
                    denominacion = denominacion.strip()

            if denominacion and denominacion in self.processed_ids:
                self.logger.info(f"Saltando duplicado (sin descargar): {denominacion}")
                return {}

            # Extraer descripción textual
            desc_section = await page.query_selector('#aContExp')
            description = ""
            if desc_section:
                try:
                    parent = await desc_section.evaluate_handle('el => el.parentElement.parentElement')
                    fieldset = await parent.query_selector('fieldset')
                    if fieldset:
                        description = await fieldset.inner_text()
                        description = description.strip()
                except: pass

            # Expandir sección de otra documentación si existe
            try:
                otro_doc_link = await page.query_selector('#aContOtro')
                if otro_doc_link:
                    await otro_doc_link.click()
                    await page.wait_for_timeout(1000)
            except Exception as e:
                self.logger.warning(f"No se pudo expandir 'Otra documentación': {e}")

            # Descargar todos los documentos PDF disponibles
            downloaded_pdfs = []
            record_id = sanitize_filename(denominacion) if denominacion else "sin_nombre"
            temp_record_dir = os.path.join(self.temp_dir, record_id)

            all_links = await page.query_selector_all('a[href*="verDocumento"]')

            if all_links:
                os.makedirs(temp_record_dir, exist_ok=True)
                self.logger.info(f"Encontrados {len(all_links)} documentos para {record_id}")

            for i, link in enumerate(all_links):
                try:
                    if not await link.is_visible():
                        continue

                    async with page.expect_download(timeout=15000) as download_info:
                        await link.click()
                        await page.wait_for_timeout(500)

                    download = await download_info.value
                    path = await download.path()
                    target_path = os.path.join(temp_record_dir, f"doc_{i}.pdf")
                    shutil.copy(path, target_path)
                    downloaded_pdfs.append(target_path)
                    self.logger.info(f"Descargado documento {i+1}/{len(all_links)}")

                except Exception as e:
                    pass

            # Fusionar PDFs descargados en un único archivo
            final_pdf_path = ""
            text_content = ""

            if downloaded_pdfs:
                merged_filename = f"{record_id}.pdf"
                merged_path = os.path.join(self.pdf_folder, merged_filename)

                try:
                    merged_doc = fitz.open()
                    for pdf_file in downloaded_pdfs:
                        try:
                            doc = fitz.open(pdf_file)
                            merged_doc.insert_pdf(doc)
                            doc.close()
                        except Exception as e:
                            self.logger.warning(f"Error al unir PDF {pdf_file}: {e}")

                    merged_doc.save(merged_path)
                    merged_doc.close()
                    final_pdf_path = merged_path
                    text_content = ""
                    self.logger.info(f"PDF fusionado guardado: {merged_path}")

                except Exception as e:
                    self.logger.error(f"Error merging PDFs para {record_id}: {e}")
                    text_content = description
            else:
                text_content = description
                self.logger.info(f"No se encontraron PDFs para {record_id}, usando descripción en text")

            return {
                "id": denominacion,
                "description": description,
                "category": category,
                "ubication": ubication,
                "text": text_content,
                "pdf_path": final_pdf_path,
                "url": url
            }

        except Exception as e:
            self.logger.error(f"Error procesando detalle {url}: {e}")
            return {}
        finally:
            # Cerrar el contexto efímero
            try:
                await detail_context.close()
            except Exception as e:
                self.logger.warning(f"Error cerrando contexto de detalle: {e}")

    async def scrape(self) -> None:
        """Navega por el buscador de inmuebles y procesa cada ficha.

        Accede al buscador de la JCYL, lanza una búsqueda vacía para
        obtener todos los registros, recorre todas las páginas de resultados
        y procesa cada ficha de detalle individualmente.

        Raises:
            Exception: Si se produce un error de navegación general.
        """
        self.logger.info("=== INICIANDO SCRAPING ===")
        await self.init_browser()
        page = await self.context.new_page()

        try:
            # Acceder al buscador de inmuebles
            search_url = "https://servicios.jcyl.es/pweb/buscarInmueble.do"
            self.logger.info(f"Navegando a: {search_url}")
            await page.goto(search_url)

            # Búsqueda vacía para obtener todos los registros
            await page.click('input[value="Buscar"]')
            await page.wait_for_load_state('networkidle')

            # Iterar por todas las páginas de resultados
            has_next = True
            processed_count = 0

            while has_next:
                # Extraer enlaces a fichas de detalle de la página actual
                links = await page.evaluate('''() => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="datos.do?numero="]'));
                    return anchors.map(a => a.href);
                }''')

                # Deduplicar enlaces
                unique_links = list(set(links))
                self.logger.info(f"Encontrados {len(unique_links)} items en esta página.")

                for link in unique_links:
                    data = await self.process_detail(link)
                    if data and data.get('id'):
                        self.append_to_csv(data)
                        self.processed_ids.add(data['id'])

                    # Pequeño delay para permitir limpieza de recursos
                    await page.wait_for_timeout(500)
                    processed_count += 1

                # Verificar si hay página siguiente
                next_btn = page.get_by_title("Siguiente", exact=False).or_(page.get_by_text("Siguiente", exact=True))

                if await next_btn.count() > 0 and await next_btn.first.is_visible():
                    await next_btn.first.click()
                    await page.wait_for_load_state('networkidle')
                else:
                    has_next = False

        except Exception as e:
            self.logger.error(f"Error en flujo principal: {e}")
        finally:
            await self.close()
            self.postprocess()

    def append_to_csv(self, data: dict) -> None:
        """Añade un nuevo registro al archivo CSV de salida.

        Filtra los campos del diccionario a las columnas definidas y escribe
        la cabecera si el archivo no existe aún.

        Args:
            data: Diccionario con los metadatos del inmueble procesado.
        """
        file_exists = os.path.exists(self.csv_path)
        keys = ["id", "description", "category", "ubication", "text", "pdf_path", "url"]
        filtered_data = {k: data.get(k, "") for k in keys}

        try:
            with open(self.csv_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(filtered_data)
        except Exception as e:
            self.logger.error(f"Error escribiendo CSV: {e}")

    def postprocess(self) -> None:
        """Postprocesa el CSV y genera el Parquet final con las columnas seleccionadas.

        Lee el CSV, garantiza que existen las columnas finales requeridas
        (añadiéndolas vacías si faltan), selecciona únicamente esas columnas
        y escribe el resultado en un archivo Parquet.
        """
        try:
            df = pl.read_csv(self.csv_path)
            final_cols = ["id", "description", "category", "ubication", "text"]

            for col in final_cols:
                if col not in df.columns:
                    df = df.with_columns(pl.lit("").alias(col))

            df = df.select(final_cols)
            output_parquet = os.path.join(self.dataset_folder, "output.parquet")
            df.write_parquet(output_parquet)
            self.logger.info(f"Creado parquet en {output_parquet}")
        except Exception as e:
            self.logger.error(f"Error en postprocess: {e}")


if __name__ == "__main__":
    # Crear instancia del recolector de datos
    scraper = JcylScraper(
        config_path="config.yaml",
        folders=["ALIA", "Castilla y Leon"]
    )

    # Ejecutar proceso de recolección
    asyncio.run(scraper.scrape())
