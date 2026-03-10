"""Recolector de datos OAI-PMH para la Revista Riparia.

Este módulo recolecta artículos de la Revista Riparia (Universidad de Cádiz) mediante OAI-PMH.

Example:
    python scraper_heritage_UniversidadDeCadiz_RevistaRiparia.py
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


def sanitize_filename(filename: str) -> str:
    """
    Limpia una cadena para que sea un nombre válido para un archivo.
    Reemplaza o elimina caracteres inválidos comunes en Windows, macOS y Linux.

    Args:
        filename: Nombre original del archivo.

    Returns:
        Nombre seguro para usar en rutas de archivos.
    """
    # Define caracteres inválidos comunes (Windows especialmente)
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
    # Reemplaza caracteres inválidos por guion bajo
    sanitized = re.sub(invalid_chars, '_', filename)

    # Opcional: elimina espacios al inicio y final, y limita longitud si quieres
    sanitized = sanitized.strip()

    # También evita nombres reservados de Windows (como CON, PRN, AUX...)
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
    """Recolector de datos OAI-PMH para la Revista Riparia.

    Attributes:
        dataset_folder: Ruta a la carpeta raíz del dataset.
        pdf_folder: Ruta a la subcarpeta de PDFs.
        epub_folder: Ruta a la subcarpeta de EPUBs.
        docx_folder: Ruta a la subcarpeta de DOCXs.
        csv_path: Ruta al CSV de salida.
        logger: Logger configurado.
        urls: URL del endpoint OAI-PMH.

    Example:
        >>> Scraper("config.yaml", ["ALIA", "Revista_Riparia"],
        ...         "https://revistas.uca.es/index.php/sig/oai").execute()
    """

    def __init__(self, config_path: str, folders: list[str], urls: str) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al YAML de configuración.
            folders: Carpetas anidadas del dataset.
            urls: URL del endpoint OAI-PMH.

        Raises:
            RuntimeError: Si falla la carga de configuración.
            win32net.error: Si falla la conexión a red.
        """
        config = OmegaConf.load(config_path)
        netresource = {
            'remote': config.disk_path,
            'password': config.password,
            'user': config.user
        }
        win32net.NetUseAdd(None, 2, netresource)

        self.dataset_folder = os.path.join(config.disk_path, *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        self.pdf_folder = os.path.join(self.dataset_folder, "pdfs")
        os.makedirs(self.pdf_folder, exist_ok=True)
        self.epub_folder = os.path.join(self.dataset_folder, "epubs")
        os.makedirs(self.epub_folder, exist_ok=True)
        self.docx_folder = os.path.join(self.dataset_folder, "docx")
        os.makedirs(self.docx_folder, exist_ok=True)

        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.logger = self.setup_logger()
        self.urls = urls

    def is_direct_document(self, url: str) -> tuple[bool, str]:
        """Check if URL points directly to PDF, EPUB, or DOCX"""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.head(url, allow_redirects=True, headers=headers, timeout=10)
            content_type = resp.headers.get("Content-Type", "").lower()
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
            resp = requests.get(url, stream=True, headers=headers)
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
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip()
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

    async def extract_pdf_from_page(self, page_url: str, base_name: str) -> str:
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
        """Extrae información de los registros de open archive initiative
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }
        sickle = Sickle(self.urls, headers=headers)
        try:
            records = sickle.ListRecords(metadataPrefix='oai_dc')
            # Procesar todos los registros secuencialmente
            for record in records:
                if record.deleted:
                    self.logger.info("Registro eliminado omitido.")
                    continue  # Ignorar registros eliminados
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
                base_name = sanitize_filename(title)
                if len(base_name) > 100:
                    base_name = base_name[:100].rstrip('_')

                pdf_text = ""
                for rel in relation:
                    if rel.startswith('http'):
                        is_doc, doc_type = self.is_direct_document(rel)
                        if is_doc:
                            folder_map = {"pdf": self.pdf_folder, "epub": self.epub_folder, "docx": self.docx_folder}
                            path = self.download_file(rel, folder_map[doc_type], base_name, doc_type)
                            if not path:
                                continue
                            if doc_type == "pdf":
                                pdf_text = self.extract_text_from_pdf(path)
                            elif doc_type == "epub":
                                pdf_text = self.extract_text_from_epub(path)
                            elif doc_type == "docx":
                                pdf_text = self.extract_text_from_docx(path)
                        else:
                            pdf_text = await self.extract_pdf_from_page(rel, base_name)

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
                    "source":source or "",
                    "format": article_format,
                    "subject": subject,
                    "text": pdf_text or ""
                }

                self.append_record(record_data)

        except Exception as e:
            self.logger.error(f"Error al explorar enlace: {e}")

    def postprocess(self) -> None:
        df = pl.read_csv(self.csv_path, encoding="utf-8")
        df = df.drop_nulls(subset=["text"])
        df = df.unique(subset=["text"])
        df = df.unique(subset=["id"], keep="first")
        df = df.fill_null("")
        df.write_parquet(os.path.join(self.dataset_folder, "output.parquet"))
        self.logger.info(f"Postprocesado finalizado. Registros únicos con texto: {df.height}")

    def setup_logger(self) -> logging.Logger:
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
        asyncio.run(self.process_registers())
        self.postprocess()

if __name__ == "__main__":
    scraper = Scraper(
        config_path="config.yaml",
        folders=["ALIA", "Revista_Riparia"],
        urls="https://revistas.uca.es/index.php/sig/oai"
    )
    scraper.execute()
            
            