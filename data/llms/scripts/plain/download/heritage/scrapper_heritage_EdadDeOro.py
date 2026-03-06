"""Recolector de datos web para la Revista Edad de Oro.

Este módulo implementa un método que recolecta información sobre artículos
de la Revista Edad de Oro de la Universidad Autónoma de Madrid mediante el
protocolo OAI-PMH. A diferencia del cliente Sickle estándar, este scraper
utiliza Playwright para superar protecciones WAF y extraer las cookies de
sesión necesarias para acceder al endpoint XML, parseando la respuesta con
lxml y siguiendo el token de reanudación para paginar todos los registros.

La Revista Edad de Oro contiene:
    - Artículos de investigación sobre literatura española del Siglo de Oro
    - Estudios sobre teatro, poesía y prosa de los siglos XVI y XVII
    - Publicaciones de acceso abierto de la UAM

Example:
    Ejecución básica::

        python scrapper_heritage_EdadDeOro.py

    Esto iterará por todos los registros OAI-PMH del repositorio, extraerá
    los metadatos y descargará los documentos correspondientes.

Note:
    Los datos son de acceso público a través del repositorio OAI-PMH de
    la Universidad Autónoma de Madrid.
    URL: https://revistas.uam.es/edadoro/oai
"""

import asyncio
import csv
import logging
import os
import re
import time
from typing import Optional

import urllib3
from omegaconf import OmegaConf
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
from docx import Document
import polars as pl
import win32net
import requests
from pdf2image import convert_from_path
import pytesseract
from PyPDF2 import PdfReader
from lxml import etree

# Deshabilitar warnings de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def sanitize_filename(filename: str) -> str:
    """
    Limpia una cadena para que sea un nombre válido para un archivo.
    """
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
    sanitized = re.sub(invalid_chars, '_', filename)
    sanitized = sanitized.strip()

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
    """Recolector de datos OAI-PMH para la Revista Edad de Oro.

    Esta clase gestiona el proceso completo de recolección de datos desde
    el repositorio OAI-PMH de la Revista Edad de Oro, utilizando Playwright
    para obtener las cookies de sesión necesarias (WAF) y lxml para parsear
    el XML de las respuestas. Soporta paginación mediante ``resumptionToken``.

    Attributes:
        dataset_folder: Ruta a la carpeta raíz del dataset.
        pdf_folder: Ruta a la subcarpeta de PDFs descargados.
        epub_folder: Ruta a la subcarpeta de EPUBs descargados.
        docx_folder: Ruta a la subcarpeta de DOCXs descargados.
        csv_path: Ruta al archivo CSV de salida.
        logger: Logger configurado para el recolector.
        urls: URL del endpoint OAI-PMH del repositorio.
        cookies: Diccionario de cookies de sesión obtenidas con Playwright.

    Example:
        >>> scraper = Scraper(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Revista_Edad_De_Oro"],
        ...     urls="https://revistas.uam.es/edadoro/oai"
        ... )
        >>> scraper.execute()
    """

    def __init__(self, config_path: str, folders: list[str], urls: str) -> None:
        """Inicializa el recolector de datos.

        Carga la configuración, monta el disco de red, crea las carpetas
        necesarias y configura el logger.

        Args:
            config_path: Ruta al archivo YAML de configuración con
                credenciales del disco de red.
            folders: Lista de carpetas anidadas para crear la estructura
                del dataset (ej: ['ALIA', 'Revista_Edad_De_Oro']).
            urls: URL del endpoint OAI-PMH del repositorio.

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

        # Subcarpetas para cada tipo de documento
        self.pdf_folder = os.path.join(self.dataset_folder, "pdfs")
        os.makedirs(self.pdf_folder, exist_ok=True)
        self.epub_folder = os.path.join(self.dataset_folder, "epubs")
        os.makedirs(self.epub_folder, exist_ok=True)
        self.docx_folder = os.path.join(self.dataset_folder, "docx")
        os.makedirs(self.docx_folder, exist_ok=True)

        # Rutas de archivos y configuración
        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.logger = self.setup_logger()
        self.urls = urls
        self.cookies = {}

    def is_direct_document(self, url: str) -> tuple[bool, str]:
        """Check if URL points directly to PDF, EPUB, or DOCX"""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            resp = requests.head(url, allow_redirects=True, headers=headers, cookies=self.cookies, verify=False, timeout=10)
            content_type = resp.headers.get("Content-Type", "").lower()
            
            self.logger.info(f"Checking URL: {url} | Status: {resp.status_code} | Type: {content_type}")
            
            if "application/pdf" in content_type:
                return True, "pdf"
            elif "application/epub+zip" in content_type or url.lower().endswith(".epub"):
                return True, "epub"
            elif ("application/vnd.openxmlformats-officedocument.wordprocessingml.document" in content_type
                  or url.lower().endswith(".docx")):
                return True, "docx"
            else:
                return False, ""
        except Exception as e:
            self.logger.warning(f"No se pudo verificar tipo de documento URL ({url}): {e}")
            return False, ""


    def download_file(self, url: str, folder: str, name: str, ext: str) -> str:
        """Download and save file. Returns full path or empty string if failed."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                "Accept": "*/*"
            }
            resp = requests.get(url, stream=True, verify=False, headers=headers, cookies=self.cookies, timeout=30)
            if resp.status_code == 200:
                ruta = os.path.join(folder, f"{name}.{ext}")
                with open(ruta, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024):
                        f.write(chunk)
                self.logger.info(f"{ext.upper()} descargado: {ruta}")
                return ruta
            else:
                self.logger.warning(f"Archivo no válido o no encontrado: {url} (status {resp.status_code})")
                return ""
        except Exception as e:
            self.logger.error(f"Error al descargar {url}: {e}")
            return ""

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        try:
            pdf_reader = PdfReader(pdf_path)
            extracted_text = ""

            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + "\n"

            if not extracted_text.strip():
                self.logger.info(f"Texto vacío con PyPDF2, intentando OCR para {pdf_path}")
                images = convert_from_path(pdf_path)
                ocr_text = ""
                for img in images:
                    ocr_text += pytesseract.image_to_string(img) + "\n"
                return ocr_text.strip()

            return extracted_text.strip()

        except Exception as e:
            self.logger.error(f"Error extrayendo texto del PDF {pdf_path}: {e}")
            return ""

    def extract_text_from_epub(self, epub_path: str) -> str:
        try:
            book = epub.read_epub(epub_path)
            texts = []
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), features='html.parser')
                    texts.append(soup.get_text())
            return "\n".join(texts).strip()
        except Exception as e:
            self.logger.error(f"Error extrayendo texto del EPUB {epub_path}: {e}")
            return ""

    def extract_text_from_docx(self, docx_path: str) -> str:
        try:
            doc = Document(docx_path)
            fullText = []
            for para in doc.paragraphs:
                fullText.append(para.text)
            return "\n".join(fullText).strip()
        except Exception as e:
            self.logger.error(f"Error extrayendo texto del DOCX {docx_path}: {e}")
            return ""

    def extract_text(self, path: str, doc_type: str) -> str:
        """Extrae el texto de un documento según su tipo.

        Despacha la extracción al método específico según el tipo de archivo.

        Args:
            path: Ruta al archivo del que extraer el texto.
            doc_type: Tipo de documento: ``'pdf'``, ``'epub'`` o ``'docx'``.

        Returns:
            Texto extraído del documento, o cadena vacía si el tipo no
            es reconocido o si ocurrió un error.
        """
        if doc_type == "pdf":
            return self.extract_text_from_pdf(path)
        elif doc_type == "epub":
            return self.extract_text_from_epub(path)
        elif doc_type == "docx":
            return self.extract_text_from_docx(path)
        return ""

    async def extract_pdf_from_page(self, page_url: str, base_name: str) -> str:
        try:
            self.logger.info(f"Navegando a visor para descarga interactiva: {page_url}")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                
                # Configurar cookies para mantener sesión (WAF/Auth)
                import urllib.parse
                domain = urllib.parse.urlparse(self.urls).netloc
                pw_cookies = []
                for name, value in self.cookies.items():
                    pw_cookies.append({
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": "/"
                    })

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                )
                if pw_cookies:
                    await context.add_cookies(pw_cookies)
                
                page = await context.new_page()

                try:
                    await page.goto(page_url, wait_until="networkidle", timeout=60000)
                except Exception as e:
                    self.logger.error(f"Timeout o error cargando {page_url}: {e}")
                    await browser.close()
                    return ""

                # Estrategia de selectores para el botón de descarga
                # Prioridad 1: Selector específico del usuario
                # Prioridad 2: Selectores genéricos de OJS
                selectors = [
                    "a.btn.btn-primary[download]", 
                    "a.obj_galley_link", 
                    "a:has-text('Descargar')",
                    "a:has-text('PDF')",
                    "a[href*='/article/download/']"
                ]
                
                download_button = None
                for sel in selectors:
                    if await page.is_visible(sel):
                        download_button = page.locator(sel).first
                        self.logger.info(f"Botón de descarga encontrado con selector: {sel}")
                        break
                
                if not download_button:
                    # Intento desesperado: buscar cualquier enlace que contenga 'download' y parezca botón
                    self.logger.warning("Selectores primarios fallaron. Buscando genérico...")
                    download_button = page.locator("a[href*='download']").first
                    if not await download_button.is_visible():
                         self.logger.error(f"No se encontró botón de descarga en {page_url}")
                         await browser.close()
                         return ""

                # Simular clic y esperar descarga
                try:
                    async with page.expect_download(timeout=60000) as download_info:
                        # A veces es necesario un pequeño scroll o delay
                        await download_button.scroll_into_view_if_needed()
                        await asyncio.sleep(1)
                        await download_button.click()
                    
                    download = await download_info.value
                    
                    # Determinar extensión y carpeta
                    ext = "pdf"
                    suggested = download.suggested_filename
                    if suggested and suggested.lower().endswith(".epub"): ext = "epub"
                    elif suggested and suggested.lower().endswith(".docx"): ext = "docx"
                    
                    folder_map = {"pdf": self.pdf_folder, "epub": self.epub_folder, "docx": self.docx_folder}
                    final_path = os.path.join(folder_map.get(ext, self.pdf_folder), f"{base_name}.{ext}")
                    
                    # Guardar archivo
                    await download.save_as(final_path)
                    self.logger.info(f"Archivo descargado correctamente: {final_path}")
                    
                    await browser.close()
                    return self.extract_text(final_path, ext)

                except Exception as e:
                    self.logger.error(f"Error durante la interacción de descarga en {page_url}: {e}")
                    await browser.close()
                    return ""

        except Exception as e:
            self.logger.error(f"Error global en extract_pdf_from_page: {e}")
            return ""

        except Exception as e:
            self.logger.error(f"Error al extraer documento desde página {page_url}: {e}")
            return ""

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

    async def fetch_oai_with_playwright(self, url: str) -> Optional[str]:
        """Obtiene el contenido XML de una URL OAI-PMH superando protecciones WAF.

        Utiliza Playwright para cargar la página del repositorio, extraer las
        cookies de sesión y luego realizar la petición GET real con ``requests``
        incluyendo dichas cookies, de forma que el servidor reconoce la sesión
        y devuelve el XML en lugar de una página de desafío.

        Args:
            url: URL del endpoint OAI-PMH con los parámetros de consulta
                (p. ej. ``?verb=ListRecords&metadataPrefix=oai_dc``).

        Returns:
            Contenido XML de la respuesta como cadena de texto, o ``None``
            si no se pudo obtener el XML o si el servidor devuelve HTML.
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (compatible; OAI-PMH Harvester/2.0)",
                    extra_http_headers={
                        "Accept": "application/xml,text/xml,*/*",
                        "Accept-Encoding": "identity"
                    }
                )
                page = await context.new_page()

                # Paso 1: cargar challenge
                await page.goto(self.urls, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)

                # Paso 2: extraer cookies del navegador
                cookies = await context.cookies()
                # Store as dict for requests
                self.cookies = {c['name']: c['value'] for c in cookies}
                
                cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                self.logger.info(f"Cookies obtenidas: {cookie_header}")

                # Paso 3: usar cookies en una petición requests final
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; OAI-PMH Harvester/2.0)",
                    "Accept": "application/xml,text/xml,*/*",
                    "Cookie": cookie_header
                }

                resp = requests.get(url, headers=headers, verify=False, timeout=30)

                if resp.status_code == 200 and "<OAI-PMH" in resp.text:
                    return resp.text

                self.logger.error("El servidor sigue devolviendo HTML en vez de XML.")
                self.logger.error(resp.text[:500])
                return None

        except Exception as e:
            self.logger.error(f"Error en fetch OAI: {e}")
            return None

    async def process_registers(self) -> None:
        """Extrae información de los registros de open archive initiative usando Playwright"""
        try:
            self.logger.info(f"Conectando a OAI-PMH endpoint: {self.urls}")
            
            # Primera petición: ListRecords
            list_records_url = f"{self.urls}?verb=ListRecords&metadataPrefix=oai_dc"
            xml_content = await self.fetch_oai_with_playwright(list_records_url)
            
            if not xml_content:
                self.logger.error("No se pudo obtener el XML del endpoint")
                return
            
            # Parsear XML
            try:
                root = etree.fromstring(xml_content.encode('utf-8'))
                namespaces = {
                    'oai': 'http://www.openarchives.org/OAI/2.0/',
                    'oai_dc': 'http://www.openarchives.org/OAI/2.0/oai_dc/',
                    'dc': 'http://purl.org/dc/elements/1.1/'
                }
            except Exception as e:
                self.logger.error(f"Error al parsear XML: {e}")
                return
            
            record_count = 0
            
            while True:
                # Buscar todos los registros en la respuesta actual
                records = root.findall('.//oai:record', namespaces)
                self.logger.info(f"Encontrados {len(records)} registros en esta página")
                
                for record in records:
                    try:
                        record_count += 1
                        self.logger.info(f"Procesando registro #{record_count}")
                        
                        # Verificar si está eliminado
                        header = record.find('oai:header', namespaces)
                        if header is not None and header.get('status') == 'deleted':
                            self.logger.info("Registro eliminado omitido.")
                            continue
                        
                        # Extraer metadata
                        metadata = record.find('.//oai_dc:dc', namespaces)
                        if metadata is None:
                            self.logger.warning("No se encontró metadata en el registro")
                            continue
                        
                        def get_metadata_values(tag):
                            elements = metadata.findall(f'dc:{tag}', namespaces)
                            return [el.text for el in elements if el.text]
                        
                        title = sanitize_filename(get_metadata_values('title')[0] if get_metadata_values('title') else 'Sin título')
                        if len(title) > 100:
                            title = title[:100].rstrip('_')
                        
                        creators = get_metadata_values('creator')
                        descriptions = get_metadata_values('description')
                        publisher = get_metadata_values('publisher')
                        date = get_metadata_values('date')
                        article_type = get_metadata_values('type')
                        article_format = get_metadata_values('format')
                        identifier = get_metadata_values('identifier')
                        source = get_metadata_values('source')
                        language = get_metadata_values('language')
                        relation = get_metadata_values('relation')
                        subject = get_metadata_values('subject')
                        
                        pdf_text = ""
                        for rel in relation:
                            if pdf_text == "" and rel.startswith('http'):
                                is_doc, doc_type = self.is_direct_document(rel)
                                if is_doc:
                                    folder_map = {"pdf": self.pdf_folder, "epub": self.epub_folder, "docx": self.docx_folder}
                                    path = self.download_file(rel, folder_map[doc_type], title, doc_type)
                                    if not path:
                                        continue
                                
                                    self.logger.info(f"Tipo de documento: {doc_type}")
                                    self.logger.info(f"Inicio lectura {doc_type.upper()}")
                                    pdf_text = self.extract_text(path, doc_type)

                                else:
                                    pdf_text = await self.extract_pdf_from_page(rel, title)
                        
                        record_data = {
                            "id": title,
                            "url": relation,
                            "author": creators,
                            "description": descriptions,
                            "publisher": publisher,
                            "language": language,
                            "date": date,
                            "type": article_type,
                            "identifier": identifier,
                            "source": source or "",
                            "format": article_format,
                            "subject": subject,
                            "text": pdf_text or ""
                        }

                        self.append_record(record_data)
                        
                    except Exception as e:
                        self.logger.error(f"Error procesando registro individual: {e}")
                        continue
                
                # Buscar resumptionToken para continuar
                resumption_token = root.find('.//oai:resumptionToken', namespaces)
                
                if resumption_token is not None and resumption_token.text:
                    self.logger.info(f"Continuando con resumptionToken: {resumption_token.text[:50]}...")
                    next_url = f"{self.urls}?verb=ListRecords&resumptionToken={resumption_token.text}"
                    xml_content = await self.fetch_oai_with_playwright(next_url)
                    
                    if not xml_content:
                        self.logger.warning("No se pudo obtener la siguiente página")
                        break
                    
                    try:
                        root = etree.fromstring(xml_content.encode('utf-8'))
                    except Exception as e:
                        self.logger.error(f"Error al parsear siguiente página XML: {e}")
                        break
                    
                    # Pequeña pausa entre peticiones
                    await asyncio.sleep(2)
                else:
                    self.logger.info("No hay más páginas (sin resumptionToken)")
                    break

            self.logger.info(f"Procesamiento completado. Total de registros procesados: {record_count}")

        except Exception as e:
            self.logger.error(f"Error al explorar enlace: {e}")
            import traceback
            self.logger.error(f"Traceback completo:\n{traceback.format_exc()}")

    def postprocess(self) -> None:
        """Postprocesa el CSV eliminando duplicados y nulos, y genera el Parquet.

        Lee el CSV de salida, elimina registros sin texto, deduplica por
        contenido de texto e ID, rellena nulos con cadena vacía y escribe
        el resultado en un archivo Parquet.
        """
        try:
            if not os.path.exists(self.csv_path):
                self.logger.warning(f"No se encontró el archivo CSV: {self.csv_path}")
                return

            df = pl.read_csv(self.csv_path, encoding="utf-8")
            df = df.drop_nulls(subset=["text"])
            df = df.unique(subset=["text"])
            df = df.unique(subset=["id"], keep="first")
            df = df.fill_null("")
            df.write_parquet(os.path.join(self.dataset_folder, "output.parquet"))
            self.logger.info(f"Postprocesado finalizado. Registros únicos con texto: {df.height}")
        except Exception as e:
            self.logger.error(f"Error en postprocesado: {e}")

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

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Lanza la iteración asíncrona sobre los registros OAI-PMH y,
        al finalizar, realiza el postprocesado para generar el Parquet.
        """
        asyncio.run(self.process_registers())
        self.postprocess()

if __name__ == "__main__":
    # Crear instancia del recolector de datos
    scraper = Scraper(
        config_path="config.yaml",
        folders=["ALIA", "Revista_Edad_De_Oro"],
        urls="https://revistas.uam.es/edadoro/oai"
    )

    # Ejecutar proceso de recolección
    scraper.execute()