"""Recolector de datos OAI-PMH para la Revista Anales de Historia del Arte.

Este módulo recolecta artículos de la Revista Anales de Historia del Arte
(Universidad Complutense de Madrid) mediante OAI-PMH utilizando el cliente Sickle.

Example:
    python scraper_heritage_UniversidadComplutenseDeMadrid_RevistaAnalesDeHistoriaDelArte.py
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
    """Recolector de datos OAI-PMH para la Revista Anales de Historia del Arte.

    Attributes:
        dataset_folder: Ruta a la carpeta raíz del dataset.
        pdf_folder: Ruta a la subcarpeta de PDFs.
        csv_path: Ruta al CSV de salida.
        logger: Logger configurado.
        urls: URL del endpoint OAI-PMH.

    Example:
        >>> Scraper("config.yaml", ["ALIA", "Revista_AnalesDeHistoriaDelArte"],
        ...         "https://revistas.ucm.es/index.php/ANHA/oai").execute()
    """

    def __init__(self, config_path: str, folders: list[str], urls: dict) -> None:
        """Genera la instancia del scraper creando las carpetas necesarias, configurando un logger y
        declarando las variables compartidas principales.

        Args:
            config_path: Ruta al archivo de configuración YAML.
            folders: Lista de nombres de carpetas a crear recursivamente en el disco.
            urls: URL o diccionario de enlaces sobre las que aplicar web scraping.
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

        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.logger = self.setup_logger()
        self.urls = urls

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extrae texto desde un archivo PDF usando PyMuPDF.

        Args:
            pdf_path: Ruta al archivo PDF.

        Returns:
            Texto plano extraído del PDF.
        """
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

    def download_pdf(self, pdf_url, name):
        """Descarga el pdf del atículo.
            
            Args:
                pdf_url: Link al pdf
                name: Nombre con el que se guardará
        """
        try:
            resp = requests.get(pdf_url, stream=True)
            if resp.status_code == 200 and 'application/pdf' in resp.headers.get('Content-Type', ''):
                ruta = os.path.join(self.pdf_folder, name + ".pdf")
                with open(ruta, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024):
                        f.write(chunk)
                print(f"PDF descargado: {ruta}")
            else:
                print(f"PDF no válido o no encontrado: {pdf_url} (status {resp.status_code})")
        except Exception as e:
            print(f"Error al descargar {pdf_url}: {e}")

    async def extract_url(self, url_vis, base_name):
        """Obtiene la url del pdf
            
            Args:
                url_vis: Url de los metadatos
                base_name: Nombre del pdf
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url_vis, timeout=60000)

                await page.wait_for_selector("a.download", timeout=10000)
                enlace = await page.query_selector("a.download")

                if enlace:
                    href = await enlace.get_attribute("href")
                    if href and (href.endswith(".pdf") or "download" in href):
                        print(f"PDF encontrado: {href}")
                        self.download_pdf(href, base_name)
                    else:
                        print(f"Enlace encontrado, pero no parece PDF: {href}")
                else:
                    print(f"No se encontró <a class='download'> en {url_vis}")

                await browser.close()
        except Exception as e:
            print(f"Error con Playwright en {url_vis}: {e}")

    def append_record(self, record_data: dict) -> None:
        """Añade una nueva fila al fichero CSV.
        
        Args:
            record_data: Diccionario con el registro a añadir.
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

    
    def execute(self) -> None:
        """Ejecuta el proceso de scraping.
        """

        asyncio.run(self.process_registers())

        self.postprocess()

    
    async def process_registers(self) -> None:
        """Extrae información de los registros de open archive initiative
        """

        sickle = Sickle(self.urls)
        try:
            records = sickle.ListRecords(metadataPrefix='oai_dc')
            # Procesar todos los registros secuencialmente
            for record in records:
                metadata = record.metadata
                title = metadata.get('title', ['sin_titulo'])[0]
                creators = metadata.get('creator', [])
                descriptions = metadata.get('description', [])
                publisher = metadata.get('publisher', [])
                date = metadata.get('date', [])
                article_type = metadata.get('type', [])
                article_format = metadata.get('format', [])
                identifier = metadata.get('identifier', [])
                source = metadata.get('source', [])
                language = metadata.get('language', [])
                relation = metadata.get('relation', [])
                subject = metadata.get('subject', [])
                base_name = sanitize_filename(title)
                if len(base_name) > 100:
                    base_name = base_name[:100].rstrip('_')
                for i, rel in enumerate(relation):
                    if rel.startswith('http'):
                        pdf_name = base_name
                        await self.extract_url(rel, pdf_name)
                    pdf_text = self.extract_text_from_pdf(os.path.join(self.pdf_folder, base_name + ".pdf"))
                # Crear el diccionario con los datos extraídos
                record_data = {
                    "id": title,
                    "url": relation,
                    "author": creators,
                    "description": descriptions,
                    "publisher": publisher,
                    "language": language,
                    "date": date,
                    "type": article_type,
                    "format": article_format,
                    "identifier": identifier,
                    "source":source or "",
                    "subject": subject,
                    "text": pdf_text or ""
                }

                # Guardar el registro en el archivo CSV
                self.append_record(record_data)

        except Exception as e:
            self.logger.error(f"Error al explorar enlace")

    def postprocess(self) -> None:
        """Realiza el postprocesado del CSV generado, eliminando duplicados y filas sin texto.
        """

        df = pl.read_csv(self.csv_path, encoding="utf-8")
        df = df.drop_nulls(subset=["text"])
        df = df.unique(subset=["text"])

        df = df.unique(subset=["id"], keep="first")
        df = df.fill_null("")

        df.write_parquet(os.path.join(self.dataset_folder, "output.parquet"))
        self.logger.info(f"Postprocesado finalizado. Registros únicos con texto: {df.height}")

    def setup_logger(self) -> logging.Logger:
        """Configura el logger para registrar la ejecución del script.
        
        Returns:
            Logger configurado.
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
    # Crear instancia del scraper indicando configuración personal, carpetas y URL de origen
    scraper = Scraper(
        config_path="config.yaml",
        folders=["ALIA", "Patrimonio_Anales_De_Historia_Del_Arte"],
        urls="https://revistas.ucm.es/index.php/ANHA/oai" 
    )

    # Ejecutar proceso de scraping
    scraper.execute()
            