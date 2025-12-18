"""Scraper para extraer y procesar artículos de revistas CSIC.

Este módulo implementa un scraper que utiliza el protocolo OAI-PMH para
descargar artículos en PDF de revistas CSIC, extraer su contenido de texto
y almacenar la información en formato CSV y Parquet.

Uso típico:
    scraper = RevistaCSICScraper(dataset_name="Revistas_CSIC")
    scraper.extract_records(url)
    scraper.postprocess()
"""

import csv
import io
import logging
import os
import re
import unicodedata
from urllib.parse import urlparse

import fitz
import pdfplumber
import polars as pl
import pytesseract
import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from sickle import Sickle
from urllib3.util.retry import Retry


class RevistaCSICScraper:
    """Scraper para procesar y descargar artículos de revistas CSIC.
    
    Attributes:
        dataset_name: Nombre del dataset a procesar.
        main_folder: Ruta de la carpeta principal del proyecto.
        headers: Cabeceras HTTP para las peticiones.
        logger: Logger para registrar eventos del scraper.
        pdf_folder: Carpeta donde se guardan los PDFs descargados.
        csv_path: Ruta del archivo CSV de salida.
        downloaded_ids: Set con IDs de documentos ya descargados.
    """

    def __init__(self, dataset_name: str):
        """Inicializa el scraper con la configuración necesaria.
        
        Args:
            dataset_name: Nombre identificativo del dataset.
        """
        csv.field_size_limit(10**7)
        self.dataset_name = dataset_name
        self.main_folder = os.path.join("ALIA", self.dataset_name)
        os.makedirs(self.main_folder, exist_ok=True)
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/115.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Connection': 'keep-alive'
        }
        self.logger = self._setup_logger()
        self.pdf_folder = os.path.join(self.main_folder, self.dataset_name)
        os.makedirs(self.pdf_folder, exist_ok=True)
        self.csv_path = os.path.join(self.main_folder, "output.csv")
        self.downloaded_ids = self._get_downloaded_ids()

    def _get_downloaded_ids(self):
        """Lee el CSV y devuelve un set con todos los IDs existentes.
        
        Returns:
            Set con los IDs de documentos ya procesados.
        """
        if not os.path.exists(self.csv_path):
            return set()
        try:
            with open(
                self.csv_path, 
                mode='r', 
                encoding='utf-8', 
                errors='ignore'
            ) as f:
                reader = csv.DictReader(f)
                return {row["id"] for row in reader}
        except (IOError, csv.Error) as e:
            self.logger.error(
                f"Error al leer el fichero CSV {self.csv_path}: {e}"
            )
            return set()

    def _setup_logger(self) -> logging.Logger:
        """Configura y devuelve el logger del scraper.
        
        Returns:
            Logger configurado para el dataset.
        """
        logger = logging.getLogger(self.dataset_name)
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(
                    self.main_folder, 
                    f"{self.dataset_name}.log"
                ),
                mode='w',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)
            
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        
        return logger

    def append_record(self, record_data: dict):
        """Añade una nueva fila al fichero CSV.
        
        Args:
            record_data: Diccionario con los datos del registro a añadir.
        """
        try:
            file_exists = os.path.exists(self.csv_path)
            with open(
                self.csv_path, 
                mode='a', 
                newline='', 
                encoding='utf-8'
            ) as f:
                writer = csv.DictWriter(f, fieldnames=record_data.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(record_data)
            self.logger.info(
                f"Registro con ID {record_data['id']} guardado en el CSV."
            )
        except IOError as e:
            self.logger.error(
                f"No se pudo escribir en el CSV {self.csv_path}: {e}"
            )

    @staticmethod
    def clean_filename(name: str, replacement: str = "_") -> str:
        """Limpia una cadena para convertirla en nombre de archivo válido.
        
        Elimina o reemplaza caracteres inválidos para nombres de archivo,
        normaliza caracteres Unicode y trunca la longitud.
        
        Args:
            name: Cadena original del nombre de archivo.
            replacement: Carácter con el que reemplazar caracteres inválidos.
            
        Returns:
            Nombre de archivo limpio y seguro.
        """
        clean_name = os.path.splitext(
            os.path.basename(urlparse(name).path)
        )[0]
        clean_name = unicodedata.normalize('NFKD', clean_name).encode(
            'ascii', 'ignore'
        ).decode('ascii')
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', replacement, clean_name)
        clean_name = re.sub(r'[\\/*?:"<>|]', replacement, clean_name)
        clean_name = re.sub(f'{replacement}+', replacement, clean_name)
        clean_name = clean_name.strip(replacement)
        clean_name = clean_name[:150]
        return clean_name if clean_name else "documento"

    def download_pdf(self, url: str, title: str) -> str:
        """Descarga un PDF desde la URL especificada.
        
        Args:
            url: URL del PDF a descargar.
            title: Nombre del archivo de salida.
            
        Returns:
            Ruta completa del archivo descargado.
        """
        session = requests.Session()
        retries = Retry(
            total=3, 
            backoff_factor=1, 
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        response = session.get(
            url.replace("view", "download"),
            headers=self.headers,
            stream=True,
            timeout=10
        )
        response.raise_for_status()

        full_output_path = os.path.join(self.pdf_folder, title)
        
        with open(full_output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        self.logger.info(f"PDF {title} descargado y guardado!")

    def get_pdf_content(self, pdf_path: str) -> str:
        """Extrae el contenido de texto de un archivo PDF.
        
        Args:
            pdf_path: Ruta al fichero PDF de entrada.
            
        Returns:
            Contenido de texto extraído del PDF.
        """
        text_content = ""
        try:
            pdf_document = fitz.open(pdf_path)
            text_content = self._extract_text(pdf_path, pdf_document)
            pdf_document.close()
        except Exception as e:
            self.logger.error(f"Error al procesar el PDF {pdf_path}: {e}")

        return text_content

    def _extract_text_pdfplumber(self, pdf_path):
        """Extrae texto usando pdfplumber.
        
        Args:
            pdf_path: Ruta del archivo PDF.
            
        Returns:
            Texto extraído del PDF.
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                return "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        except Exception as e:
            self.logger.error(f"pdfplumber error en {pdf_path}: {e}")
            return ""

    def _extract_text_ocr(self, pdf_document):
        """Extrae texto usando OCR con Tesseract.
        
        Args:
            pdf_document: Documento PDF abierto con fitz.
            
        Returns:
            Texto extraído mediante OCR.
        """
        ocr_text = ""
        for page in pdf_document:
            pix = page.get_pixmap(dpi=300)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_text += pytesseract.image_to_string(image, lang="spa") + "\n"
        return ocr_text

    def _extract_text(self, pdf_path: str, pdf_document: open):
        """Extrae texto del PDF usando diferentes métodos.
        
        Primero intenta con pdfplumber, si falla usa OCR como fallback.
        
        Args:
            pdf_path: Ruta del archivo PDF.
            pdf_document: Documento PDF abierto.
            
        Returns:
            Texto extraído del PDF.
        """
        # Fallback con pdfplumber
        self.logger.info(f"Usando pdfplumber para extraer {pdf_path}.")
        text_content = self._extract_text_pdfplumber(pdf_path)
        if text_content != "":
            return text_content

        # Fallback con OCR
        self.logger.info(
            f"Texto aún vacío en {pdf_path}, aplicando OCR."
        )
        text_content = self._extract_text_ocr(pdf_document)
        return text_content

    def extract_records(self, url: str):
        """Extrae registros del repositorio OAI-PMH.
        
        Args:
            url: URL del endpoint OAI-PMH.
        """
        sickle = Sickle(url)
        records = sickle.ListRecords(
            metadataPrefix='oai_dc', 
            ignore_deleted=True
        )

        for record in records:
            md = record.metadata

            # Extraer todos los campos posibles
            titles = md.get('title', [""])
            creators = md.get('creator', [""])
            descriptions = md.get('description', [""])
            publisher = md.get('publisher', [''])
            date = md.get('date', [""])
            types = md.get('type', [""])
            sources = md.get('source', [""])
            languages = md.get('language', [""])
            identifiers = md.get('identifier', [""])
            relations = md.get('relation', [""])
            
            # Identificar URLs relevantes
            url_article = next(
                (i for i in identifiers if '/article/view/' in i), 
                ''
            )
            url_pdf = next(
                (r for r in relations if '/article/view/' in r), 
                ''
            )
            doi = next((i for i in identifiers if i.startswith('10.')), '')
            record_id = f"{sources[0]}.pdf"
            
            if record_id not in self.downloaded_ids and url_pdf != "":
                self.download_pdf(url_pdf, record_id)
                text = self.get_pdf_content(
                    os.path.join(self.pdf_folder, record_id)
                )

                article_fields = [
                    field.strip() for field in sources[0].split(';')
                ]

                def get_field(fields, index, default=""):
                    """Obtiene un campo de la lista o devuelve default."""
                    return (
                        fields[index] 
                        if len(fields) > index and fields[index] 
                        else default
                    )

                # Registrar fila
                self.append_record({
                    "id": record_id,
                    "url_pdf": url_pdf,
                    'url_article': url_article,
                    'title': titles[-1],
                    'journal': get_field(article_fields, 0),
                    'volume': get_field(article_fields, 1),
                    'pages': get_field(article_fields, 2),
                    'authors': creators,
                    'description': descriptions[-1],
                    'publisher': publisher,
                    'date': date[-1],
                    'type': types,
                    'source': sources,
                    'language': languages,
                    'doi': doi,
                    "text": text.replace('\n', ' ').strip()
                })
            else:
                self.logger.info(
                    f"PDF con id {record_id} ya ha sido descargado."
                )

    def postprocess(self):
        """Postprocesa los datos extraídos.
        
        Elimina duplicados, archivos no referenciados y genera el archivo
        Parquet final.
        """
        df = pl.read_csv(self.csv_path, encoding="utf-8")
        df = df.drop_nulls(subset=["text"])
        df = df.unique(subset=["text"])

        existing_files = set(os.listdir(self.pdf_folder))
        df = df.unique(subset=["id"], keep="first")
        referenced_files = set((df["id"]).to_list())

        unused_files = existing_files - referenced_files

        df = df.fill_null("")

        for filename in unused_files:
            file_path = os.path.join(self.pdf_folder, filename)
            try:
                os.remove(file_path)
                self.logger.info(f"Eliminado: {file_path}")
            except Exception as e:
                self.logger.error(
                    f"No se pudo eliminar {file_path}: {e}"
                )

        df.write_parquet(os.path.join(self.main_folder, "output.parquet"))


def main():
    """Función principal que ejecuta el scraper."""
    scraper = RevistaCSICScraper(dataset_name="Revistas_CSIC")
    oai_urls = [
        "https://analescervantinos.revistas.csic.es/index.php/analescervantinos/oai",
        "http://estudiosmedievales.revistas.csic.es/index.php/estudiosmedievales/oai",
        "http://aespa.revistas.csic.es/index.php/aespa/oai",
        "http://archivoespañoldearte.revistas.csic.es/index.php/aea/oai",
        "http://arqarqt.revistas.csic.es/index.php/arqarqt/oai",
        "http://estudiosgallegos.revistas.csic.es/index.php/estudiosgallegos/oai",
        "http://hispania.revistas.csic.es/index.php/hispania/oai",
        "http://hispaniasacra.revistas.csic.es/index.php/hispaniasacra/oai"
    ]
    for url in oai_urls:
        scraper.extract_records(url)
    scraper.postprocess()


if __name__ == "__main__":
    main()