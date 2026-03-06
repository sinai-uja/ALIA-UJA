"""Recolector de datos web para Cuadernos de Prehistoria y Arqueología.

Este módulo implementa un método que recolecta información sobre artículos
de la revista Cuadernos de Prehistoria y Arqueología de la Universidad de
Granada (CPAG) mediante el protocolo OAI-PMH con la biblioteca Sickle.
Los datos se extraen iterando los registros del repositorio y descargando
los documentos asociados (PDF, EPUB o DOCX).

La revista CPAG contiene:
    - Artículos de investigación arqueológica
    - Estudios de prehistoria del ámbito ibérico y mediterráneo
    - Publicaciones científicas con acceso abierto

Example:
    Ejecución básica::

        python scraper_heritage_CuadernosDePrehistoriaYArqueologia.py

    Esto iterará por todos los registros OAI-PMH del repositorio, extraerá
    los metadatos y descargará los documentos correspondientes.

Note:
    Los datos son de acceso público a través del repositorio OAI-PMH de
    la Universidad de Granada.
    URL: https://revistaseug.ugr.es/index.php/cpag/oai
"""


import asyncio
import csv
import logging
import os
from pydoc import synopsis

import aiohttp
import ssl
from omegaconf import OmegaConf
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
from docx import Document
from sickle import Sickle
import polars as pl
import win32net
import re
import requests
import fitz
from pdf2image import convert_from_path
import pytesseract
import cv2
import numpy as np
from PIL import Image
from PyPDF2 import PdfReader


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
    """Recolector de datos OAI-PMH para Cuadernos de Prehistoria y Arqueología.

    Esta clase gestiona el proceso completo de recolección de datos desde
    el repositorio OAI-PMH de la revista CPAG, descargando los documentos
    (PDF, EPUB, DOCX) y extrayendo su texto para su posterior análisis.

    Attributes:
        dataset_folder: Ruta a la carpeta raíz del dataset.
        pdf_folder: Ruta a la subcarpeta de PDFs descargados.
        epub_folder: Ruta a la subcarpeta de EPUBs descargados.
        docx_folder: Ruta a la subcarpeta de DOCXs descargados.
        csv_path: Ruta al archivo CSV de salida.
        logger: Logger configurado para el recolector.
        urls: URL del endpoint OAI-PMH del repositorio.

    Example:
        >>> scraper = Scraper(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Revista_Cuadernos_De_Prehistoria_Y_Arqueologia"],
        ...     urls="https://revistaseug.ugr.es/index.php/cpag/oai"
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
                del dataset (ej: ['ALIA', 'Revista_Cuadernos_De_Prehistoria_Y_Arqueologia']).
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

    def is_direct_document(self, url: str) -> tuple[bool, str]:
        """Comprueba si una URL apunta directamente a un PDF, EPUB o DOCX.

        Realiza una petición HEAD a la URL para inspeccionar el Content-Type
        de la respuesta y determinar el tipo de documento.

        Args:
            url: URL a comprobar.

        Returns:
            Tupla (es_documento, tipo) donde ``es_documento`` indica si la
            URL apunta a un documento soportado y ``tipo`` es 'pdf', 'epub',
            'docx' o cadena vacía si no es un documento soportado.
        """
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.head(url, allow_redirects=True, headers=headers, verify=False, timeout=10)
            content_type = resp.headers.get("Content-Type", "").lower()
            if "application/pdf" in content_type:
                return True, "pdf"
            elif "application/epub+zip" in content_type or url.lower().endswith(".epub"):
                return True, "epub"
            elif (("application/vnd.openxmlformats-officedocument.wordprocessingml.document" in content_type)
                  or url.lower().endswith(".docx")):
                return True, "docx"
            else:
                return False, ""
        except Exception as e:
            self.logger.warning(f"No se pudo verificar tipo de documento URL ({url}): {e}")
            return False, ""

    def download_file(self, url: str, folder: str, name: str, ext: str) -> str:
        """Descarga y guarda un archivo en disco.

        Args:
            url: URL del archivo a descargar.
            folder: Carpeta de destino donde se guardará el archivo.
            name: Nombre base del archivo (sin extensión).
            ext: Extensión del archivo (sin punto), p. ej. 'pdf', 'epub'.

        Returns:
            Ruta completa del archivo guardado, o cadena vacía si la
            descarga falló.
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                "Accept": "*/*"
            }
            resp = requests.get(url, stream=True, verify=False, headers=headers)
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
        """Extrae el texto de un archivo PDF.

        Args:
            pdf_path: Ruta al archivo PDF.

        Returns:
            Texto extraído del PDF, o cadena vacía si ocurrió un error.
        """
        try:
             pdf_reader = PdfReader(pdf_path)
             ocr_text = ""
             for page in pdf_reader.pages:
                 ocr_text += f"{page.extract_text()}" + "\n"
             return ocr_text

        except Exception as e:
            self.logger.error(f"Error extrayendo texto del PDF {pdf_path}: {e}")
            return ""

    def extract_text_from_epub(self, epub_path: str) -> str:
        """Extrae el texto de un archivo EPUB.

        Args:
            epub_path: Ruta al archivo EPUB.

        Returns:
            Texto extraído del EPUB, o cadena vacía si ocurrió un error.
        """
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
        """Extrae el texto de un archivo DOCX.

        Args:
            docx_path: Ruta al archivo DOCX.

        Returns:
            Texto extraído del DOCX, o cadena vacía si ocurrió un error.
        """
        try:
            doc = Document(docx_path)
            fullText = []
            for para in doc.paragraphs:
                fullText.append(para.text)
            return "\n".join(fullText).strip()
        except Exception as e:
            self.logger.error(f"Error extrayendo texto del DOCX {docx_path}: {e}")
            return ""

    async def extract_pdf_from_page(self, page_url: str, base_name: str) -> str:
        """Navega a una página web y extrae el texto del documento enlazado.

        Usa Playwright para visitar la URL, localiza el primer enlace que
        apunte a un PDF, EPUB o DOCX, lo descarga y extrae su texto.

        Args:
            page_url: URL de la página donde buscar el enlace de descarga.
            base_name: Nombre base para guardar el archivo descargado.

        Returns:
            Texto extraído del documento encontrado, o cadena vacía si no
            se encontró ningún documento o si ocurrió un error.
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(page_url, timeout=60000)
                enlace = await page.query_selector("a[href$='.pdf'], a[href$='.epub'], a[href$='.docx'], a[href*='download']")
                if enlace:
                    href = await enlace.get_attribute("href")
                    if href:
                        pdf_url = href if href.startswith("http") else page_url.rsplit('/', 1)[0] + "/" + href
                        is_doc, doc_type = self.is_direct_document(pdf_url)
                        if is_doc:
                            folder_map = {"pdf": self.pdf_folder, "epub": self.epub_folder, "docx": self.docx_folder}
                            ext = doc_type
                            path = self.download_file(pdf_url, folder_map[ext], base_name, ext)
                            if not path:
                                return ""
                            if ext == "pdf":
                                return self.extract_text_from_pdf(path)
                            elif ext == "epub":
                                return self.extract_text_from_epub(path)
                            elif ext == "docx":
                                return self.extract_text_from_docx(path)
                        else:
                            self.logger.warning(f"Archivo en página no es PDF, EPUB ni DOCX: {pdf_url}")
                            return ""
                    else:
                        self.logger.warning(f"No se pudo extraer href desde la página {page_url}")
                        return ""
                else:
                    self.logger.warning(f"No se encontró enlace de descarga en la página {page_url}")
                    return ""
                await browser.close()
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

    async def process_registers(self) -> None:
        """Extrae información de los registros del repositorio OAI-PMH.

        Itera sobre todos los registros disponibles en el endpoint OAI-PMH
        usando el prefijo de metadatos ``oai_dc``. Para cada registro, descarga
        el documento asociado, extrae el texto y persiste los metadatos en CSV.

        Los registros marcados como eliminados se omiten automáticamente.

        Raises:
            Exception: Si se produce un error al acceder al repositorio o
                al procesar un registro individual.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }
        sickle = Sickle(self.urls, headers=headers, verify=False)
        try:
            records = sickle.ListRecords(metadataPrefix='oai_dc')
            # Procesar todos los registros secuencialmente
            for record in records:
                if record.deleted:
                    self.logger.info("Registro eliminado omitido.")
                    continue  # Ignorar registros eliminados

                # Extraer campos de metadatos Dublin Core
                metadata = record.metadata
                title = metadata.get('title', [])[0] or []
                creators = metadata.get('creator', []) or []
                descriptions = metadata.get('description', []) or []
                publisher = metadata.get('publisher', []) or []
                date = metadata.get('date', []) or []
                article_type = metadata.get('type', []) or []
                article_format = metadata.get('format', []) or []
                identifier = metadata.get('identifier', []) or []
                source = metadata.get('source', []) or []
                language = metadata.get('language', []) or []
                relation = metadata.get('relation', []) or []
                subject = metadata.get('subject', []) or []

                # Sanitizar el título para usarlo como nombre de archivo
                base_name = sanitize_filename(title)
                if len(base_name) > 100:
                    base_name = base_name[:100].rstrip('_')

                # Intentar descargar y extraer texto del documento
                pdf_text = ""
                for rel in relation:
                    if pdf_text == "":
                        if rel.startswith('http'):
                            is_doc, doc_type = self.is_direct_document(rel)
                            if is_doc:
                                folder_map = {"pdf": self.pdf_folder, "epub": self.epub_folder, "docx": self.docx_folder}
                                path = self.download_file(rel, folder_map[doc_type], base_name, doc_type)
                                if not path:
                                    continue
                            
                                self.logger.warning(f"{doc_type}")
                                self.logger.warning(f"{pdf_text}")
                                if doc_type == "pdf":
                                    self.logger.warning(f"inicio lectura pdf")
                                    pdf_text = self.extract_text_from_pdf(path)
                                
                                elif doc_type == "epub" and pdf_text == "":
                                    self.logger.warning(f"inicio lectura epub")
                                    pdf_text = self.extract_text_from_epub(path)
                                elif doc_type == "docx" and pdf_text == "":
                                    self.logger.warning(f"inicio lectura doc")
                                    pdf_text = self.extract_text_from_docx(path)
                            else:
                            
                                pdf_text = await self.extract_pdf_from_page(rel, base_name)
                
                # Construir y persistir el registro
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
            self.logger.error(f"Error al explorar enlace: {e}")

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
        folders=["ALIA", "Revista_Cuadernos_De_Prehistoria_Y_Arqueologia"],
        urls="https://revistaseug.ugr.es/index.php/cpag/oai"
    )

    # Ejecutar proceso de recolección
    scraper.execute()