"""Método para recolectar documentos del Repositorio de Activos Digitales del IAPH (READ).

Este módulo implementa un método que recolecta documentos del
Repositorio de Activos Digitales de Andalucía del IAPH.

El método:
    - Navega por el listado paginado de resultados
    - Descarga PDFs y metadatos asociados
    - Extrae texto de los PDFs
    - Genera dataset en formato Parquet

Example:
    Ejecución básica:

        python scraper_heritage_read_iaph.py

    Esto descargará documentos y generará output.parquet.

Attributes:
    MAIN_URL (str): URL base del repositorio.
    NAV_URL (str): URL template para navegación paginada.

Note:
    El repositorio es de acceso público.
"""

import asyncio
import csv
import logging
import os
import re
import shutil
import unicodedata
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

import aiohttp
import pdfplumber
import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright


# URLs del repositorio
MAIN_URL = "https://repositorio.iaph.es"
NAV_URL = "https://repositorio.iaph.es/simple-search?query=&sort_by=score&order=desc&rpp=100&etal=1&vista=lista&start={batch}"


class DataCollector:
    """Recolector de datos del repositorio READ del IAPH.

    Gestiona la navegación, descarga de PDFs, extracción
    de metadatos y generación del dataset.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        pdf_folder: Ruta a la carpeta de PDFs.
        metadata_folder: Ruta a la carpeta de metadatos.
        parquet_path: Ruta al archivo Parquet de salida.
        logger: Logger configurado.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "READ_IAPH"]
        ... )
        >>> asyncio.run(collector.execute())
    """

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

    def __init__(
        self,
        config_path: str,
        folders: list[str]
    ) -> None:
        """Inicializa el recolector.

        Args:
            config_path: Ruta al archivo YAML de configuración.
            folders: Lista de carpetas para crear la estructura.
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
            pass  # Ya conectado

        # Estructura de carpetas
        self.dataset_folder = os.path.join(config['disk_path'], *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        # Subcarpetas
        self.pdf_folder = os.path.join(self.dataset_folder, "pdf")
        os.makedirs(self.pdf_folder, exist_ok=True)

        self.metadata_folder = os.path.join(self.dataset_folder, "metadata")
        os.makedirs(self.metadata_folder, exist_ok=True)

        # Archivos de salida
        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # IDs procesados
        self.downloaded_ids = self._get_processed_ids()

        # Logger
        self.logger = self._setup_logger()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")

    def _setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging."""
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(self.dataset_folder, f"{os.path.basename(self.dataset_folder)}.log"),
                mode='a', encoding='utf-8'
            )
            console_handler = logging.StreamHandler()

            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        return logger

    @staticmethod
    def clean_filename(name: str, replacement: str = "_") -> str:
        """Limpia un string para usarlo como nombre de archivo."""
        clean_name = os.path.splitext(os.path.basename(urlparse(name).path))[0]
        clean_name = unicodedata.normalize('NFKD', clean_name).encode('ascii', 'ignore').decode('ascii')
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', replacement, clean_name)
        clean_name = re.sub(r'[\\//*?:"<>|]', replacement, clean_name)
        clean_name = re.sub(f'{replacement}+', replacement, clean_name)
        clean_name = clean_name.strip(replacement)
        return clean_name[:150] if clean_name else "unnamed_document"

    def _get_processed_ids(self) -> set:
        """Lee el CSV y devuelve un set con IDs existentes."""
        if not os.path.exists(self.csv_path):
            return set()
        try:
            with open(self.csv_path, mode='r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                return {row["id"] for row in reader if "id" in row}
        except (IOError, csv.Error) as e:
            self.logger.error(f"Error leyendo CSV: {e}")
            return set()

    async def download_pdf_file(self, pdf_url: str, output_path: str) -> bool:
        """Descarga PDF desde URL al path especificado."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(pdf_url) as response:
                    if response.status == 200:
                        with open(output_path, "wb") as f:
                            f.write(await response.read())
                        return True
                    else:
                        self.logger.error(f"No se pudo descargar {pdf_url} (status {response.status})")
        except Exception as e:
            self.logger.error(f"Fallo al descargar {pdf_url}: {e}")
        return False

    def get_pdf_content(self, pdf_path: str) -> str:
        """Extrae texto de un PDF usando pdfplumber.

        Args:
            pdf_path: Ruta al archivo PDF.

        Returns:
            Texto extraído del PDF.
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                return "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        except Exception as e:
            self.logger.error(f"Error extrayendo texto de {pdf_path}: {e}")
            return ""

    @staticmethod
    def parse_metadata(filepath: str) -> Dict[str, Union[str, List[str], None]]:
        """Extrae campos del archivo de metadatos.

        Args:
            filepath: Ruta al archivo .txt de metadatos.

        Returns:
            Diccionario con campos extraídos.
        """
        fields_to_extract = [
            "Autor", "Municipio", "Fecha de acceso", "Fecha de subida", "Fecha",
            "URI", "Resumen", "Formato", "Idioma", "Editorial", "Derechos", "Derechos URL",
            "Fuente", "Descriptores temáticos", "Título", "Tipo de documento", "URL publicación",
            "Provincia", "Editor", "ISBN", "Signatura", "DOI", "Descripción"
        ]

        list_fields = {"Descriptores temáticos"}
        fields = {key: [] if key in list_fields else None for key in fields_to_extract}
        current_field = None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.rstrip()
                    if not line:
                        continue

                    if ':' in line:
                        possible_field, value = line.split(':', 1)
                        possible_field = possible_field.strip()
                        value = value.strip()

                        if possible_field in fields_to_extract:
                            current_field = possible_field
                            if current_field in list_fields:
                                fields[current_field].append(value)
                            else:
                                fields[current_field] = value
                            continue

                    # Continuación multilínea
                    if current_field and fields[current_field] is not None:
                        if current_field in list_fields:
                            fields[current_field].append(line.strip())
                        else:
                            fields[current_field] += ' ' + line.strip()

            # Limpiar listas vacías
            for key in list_fields:
                if not fields[key]:
                    fields[key] = None

        except Exception:
            pass

        return fields

    def append_record(self, record_data: dict) -> None:
        """Añade un registro al CSV."""
        try:
            file_exists = os.path.exists(self.csv_path)
            existing_rows = []
            existing_fieldnames = []

            if file_exists and os.path.getsize(self.csv_path) > 0:
                with open(self.csv_path, mode='r', encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f)
                    existing_fieldnames = reader.fieldnames or []
                    existing_rows = list(reader)

            new_fields = list(record_data.keys())
            all_fieldnames = existing_fieldnames.copy()

            for field in new_fields:
                if field not in all_fieldnames:
                    all_fieldnames.append(field)

            if not file_exists or set(new_fields) - set(existing_fieldnames):
                temp_path = self.csv_path + '.tmp'
                with open(temp_path, mode='w', encoding='utf-8', newline='') as out_f:
                    writer = csv.DictWriter(out_f, fieldnames=all_fieldnames)
                    writer.writeheader()
                    for row in existing_rows:
                        writer.writerow({k: row.get(k, "") for k in all_fieldnames})
                    writer.writerow({k: record_data.get(k, "") for k in all_fieldnames})
                shutil.move(temp_path, self.csv_path)
            else:
                with open(self.csv_path, mode='a', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=existing_fieldnames)
                    writer.writerow({k: record_data.get(k, "") for k in existing_fieldnames})

            self.logger.info(f"[CSV] Registro {record_data.get('id', '[sin ID]')} guardado.")

        except Exception as e:
            self.logger.error(f"Error escribiendo CSV: {e}")

    async def process_page(self, page_path: str, title: str, record_id: str) -> None:
        """Procesa una página individual del repositorio."""
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()
                await page.goto(page_path, timeout=10000)
                await asyncio.sleep(1)
                self.logger.info(f"Explorando {page_path}: {title}...")

                await page.wait_for_selector('div[class="miniaturaThumbnail"] a', timeout=1000)
                file = await page.locator('div[class="miniaturaThumbnail"] a').all()

                if file:
                    href = await file[0].get_attribute('href')
                    if href.endswith('.pdf'):
                        pdf_url = MAIN_URL + href
                        pdf_filename = self.clean_filename(pdf_url)

                        # Ya procesado
                        if pdf_filename in self.downloaded_ids:
                            self.logger.info(f"PDF {pdf_filename} ya existe, saltando.")
                            return

                        pdf_path = os.path.join(self.pdf_folder, f"{pdf_filename}.pdf")
                        await self.download_pdf_file(pdf_url, pdf_path)
                        self.logger.info(f"PDF {pdf_filename} descargado!")

                        # Descargar metadatos
                        async with page.expect_download() as download_info:
                            await page.click('img#downloadIcon[alt="Ficha"][title="Ficha"]')

                        metadata_download = await download_info.value
                        metadata_path = os.path.join(self.metadata_folder, f"{pdf_filename}.txt")
                        await metadata_download.save_as(metadata_path)
                        self.logger.info(f"Metadatos {pdf_filename} descargados!")

                        # Procesar
                        text_content = self.get_pdf_content(pdf_path)
                        if text_content:
                            record_data = {
                                "id": pdf_filename,
                                "url": pdf_url,
                                **self.parse_metadata(metadata_path),
                                "text": text_content.replace('\n', ' ').strip()
                            }
                            self.append_record(record_data)
                        else:
                            self.logger.error(f"No se pudo extraer texto del PDF {pdf_filename}.")

            except Exception as e:
                self.logger.error(f"Error procesando {page_path}: {e}")
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def nav_list(self, url: str, n_page: int) -> None:
        """Navega por una página de listado."""
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()
                await page.goto(url, timeout=10000)
                await asyncio.sleep(1)

                page_links = await page.locator('td[headers="t1"] a').all()
                for i, link in enumerate(page_links):
                    href = await link.get_attribute('href')
                    title = await link.text_content()
                    page_path = MAIN_URL + href

                    self.logger.info(f"Clicando en: {page_path}: {title}")
                    await self.process_page(page_path, title, f"read_page{n_page}_item{i}")

            except Exception as e:
                self.logger.error(f"Error navegando página {n_page}: {e}")
            finally:
                await page.close()
                await context.close()
                await browser.close()

    async def execute(self) -> None:
        """Ejecuta el proceso de scraping."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO READ IAPH")
        self.logger.info("=" * 60)

        semaphore = asyncio.Semaphore(8)

        async def sem_nav_list(url: str, n_page: int) -> None:
            async with semaphore:
                await self.nav_list(url, n_page)

        tasks = []
        for i in range(0, 211201, 100):
            n_page = int(i / 100)
            self.logger.info(f"Programando exploración página {n_page}...")
            url = NAV_URL.format(batch=i)
            tasks.append(sem_nav_list(url, n_page))

        await asyncio.gather(*tasks)

        # Postprocesar
        self.postprocess()

    def postprocess(self) -> None:
        """Postprocesa el CSV y genera Parquet."""
        if not os.path.exists(self.csv_path):
            self.logger.warning("No hay CSV para postprocesar.")
            return

        try:
            df = pl.read_csv(self.csv_path, encoding="utf-8")
            df = df.drop_nulls(subset=["text"])
            df = df.unique(subset=["text"])

            # Eliminar columnas con demasiados nulos
            for col in df.columns:
                if df[col].null_count() > 500:
                    df = df.drop(col)

            # Renombrar columnas
            rename_map = {
                "Autor": "author",
                "Fecha de acceso": "available_date",
                "Fecha de subida": "upload_date",
                "Fecha": "date",
                "URI": "uri",
                "Formato": "format",
                "Derechos": "rights",
                "Derechos URL": "url_rights",
                "Descriptores temáticos": "topics",
                "Título": "title",
                "Tipo de documento": "document_type"
            }

            existing_renames = {k: v for k, v in rename_map.items() if k in df.columns}
            df = df.rename(existing_renames)

            # Seleccionar columnas disponibles
            desired_cols = ["id", "url", "title", "author", "date", "topics",
                           "available_date", "uri", "format", "document_type",
                           "url_rights", "upload_date", "rights", "text"]
            available_cols = [c for c in desired_cols if c in df.columns]
            df = df.select(available_cols)

            df = df.unique(subset=["id"], keep="first")
            df = df.fill_null("")

            df.write_parquet(self.parquet_path)
            self.logger.info(f"Parquet generado: {self.parquet_path}")

        except Exception as e:
            self.logger.error(f"Error postprocesando: {e}")


async def main():
    csv.field_size_limit(2**28)
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "READ_IAPH"]
    )
    await collector.execute()


if __name__ == "__main__":
    asyncio.run(main())

    # EDA
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    config_path = "config.yaml"
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        parquet_path = os.path.join(config['disk_path'], "ALIA", "READ_IAPH", "output.parquet")
        if os.path.exists(parquet_path):
            df = pl.read_parquet(parquet_path)
            print(f"\n📊 Total de registros: {len(df)}")
            print(f"   Columnas: {df.columns}")
