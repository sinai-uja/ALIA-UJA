"""Recolector de datos para Somos Patrimonio.

Este módulo implementa un método que recolecta información sobre
el Patrimonio Mundial de España desde el portal SomosPatrimonio.

El portal contiene:
    - Bienes del Patrimonio Mundial en España
    - Descripciones, localizaciones, fechas de inscripción

Example:
    Ejecución básica::

        python scraper_heritage_somos_patrimonio.py

    Esto navegará por el portal, extraerá información
    y generará un archivo Parquet con metadatos.

Attributes:
    PORTAL_URL (str): URL principal del portal.

Note:
    Los datos son de acceso público.
    URL: http://www.somospatrimonio.es/patrimonio/
"""

import asyncio
import logging
import os
import re

import polars as pl
import win32net
import yaml
from playwright.async_api import async_playwright


# URL del portal
PORTAL_URL = "http://www.somospatrimonio.es/patrimonio/"


class DataCollector:
    """Recolector de datos para Somos Patrimonio.

    Esta clase gestiona el proceso completo de recolección de datos
    desde el portal Somos Patrimonio.

    Attributes:
        dataset_folder: Ruta a la carpeta del dataset.
        parquet_path: Ruta al archivo Parquet de salida.
        records_buffer: Lista de registros pendientes de escritura.
        existing_ids: Conjunto de IDs ya existentes en el Parquet.
        url: URL principal del portal.
        logger: Logger configurado para el recolector.

    Example:
        >>> collector = DataCollector(
        ...     config_path="config.yaml",
        ...     folders=["ALIA", "Somos_Patrimonio"]
        ... )
        >>> collector.execute()
    """

    def __init__(
        self,
        config_path: str,
        folders: list[str],
        url: str = None
    ) -> None:
        """Inicializa el recolector de datos.

        Args:
            config_path: Ruta al archivo YAML de configuración.
            folders: Lista de carpetas anidadas para crear la estructura.
            url: URL del portal. Si es None, usa PORTAL_URL.
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
            pass  # Ya está conectado

        # Crear estructura de carpetas
        self.dataset_folder = os.path.join(config['disk_path'], *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        # Rutas de archivos
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")

        # Buffer de registros
        self.records_buffer: list[dict] = []

        # URL principal
        self.url = url or PORTAL_URL

        # Logger
        self.logger = self.setup_logger()

        # IDs existentes
        self.existing_ids = self.get_existing_ids()

        self.logger.info(f"[Init] Dataset folder: {self.dataset_folder}")
        self.logger.info(f"[Init] IDs existentes: {len(self.existing_ids)}")

    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet."""
        path = parquet_path or self.parquet_path
        if os.path.exists(path):
            try:
                df = pl.read_parquet(path)
                return set(df["id"].to_list())
            except Exception:
                return set()
        return set()

    def append_record(self, record_data: dict) -> None:
        """Añade un nuevo registro al buffer en memoria."""
        self.records_buffer.append(record_data)

    def save_to_parquet(self) -> None:
        """Persiste los registros del buffer en el archivo Parquet."""
        if not self.records_buffer:
            return

        try:
            new_df = pl.DataFrame(self.records_buffer)

            if os.path.exists(self.parquet_path):
                existing_df = pl.read_parquet(self.parquet_path)
                combined_df = pl.concat([existing_df, new_df], how="diagonal_relaxed")
            else:
                combined_df = new_df

            combined_df.write_parquet(self.parquet_path)
            self.logger.info(f"Guardados {len(self.records_buffer)} registros")
            self.records_buffer.clear()

        except Exception as e:
            self.logger.error(f"Error guardando Parquet: {e}")

    async def extract_info(self) -> dict:
        """Extrae información de los bienes del Patrimonio Mundial.

        Returns:
            Diccionario con estadísticas.
        """
        stats = {"sections_found": 0, "sections_new": 0, "errors": 0}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.url, timeout=30000)

                sections = await page.query_selector_all("div.row.section.images")
                stats["sections_found"] = len(sections)

                for sec in sections:
                    sec_id = await sec.get_attribute("id")
                    try:
                        title_el = await sec.query_selector("div.image-title h1, div.image-title h2, div.image-title")
                        if not title_el:
                            continue

                        title = (await title_el.inner_text()).strip()

                        # Localización
                        loc_el = await sec.query_selector("div.image-location")
                        location = ""
                        if loc_el:
                            loc_raw = (await loc_el.inner_text()).strip()
                            if ":" in loc_raw:
                                location = loc_raw.split(":", 1)[1].strip()
                            else:
                                location = re.sub(r'(?i)localizaci[oó]n\s*', '', loc_raw).strip()

                        # Fechas de inscripción/extensión
                        subtitle_el = await sec.query_selector("div.image-subtitle")
                        registration_date = extension_date = ""
                        if subtitle_el:
                            subtitle = (await subtitle_el.inner_text()).strip()
                            years = re.findall(r'(\d{4})', subtitle)
                            if len(years) >= 1:
                                registration_date = years[0]
                            if len(years) >= 2:
                                extension_date = years[1]

                        # Descripción
                        desc_el = await sec.query_selector("div.image-description")
                        text = (await desc_el.inner_text()).strip() if desc_el else ""

                        # ID normalizado
                        rec_id = sec_id.replace("image-", "") if sec_id and sec_id.startswith("image-") else sec_id
                        item_id = f"sp_{rec_id}"

                        if item_id in self.existing_ids:
                            continue

                        self.append_record({
                            "id": item_id,
                            "title": title,
                            "location": location,
                            "registration_date": registration_date,
                            "extension_date": extension_date,
                            "text": text
                        })
                        self.existing_ids.add(item_id)
                        stats["sections_new"] += 1

                    except Exception as e:
                        self.logger.error(f"Error en sección {sec_id}: {e}")
                        stats["errors"] += 1

            except Exception as e:
                self.logger.error(f"Error cargando página: {e}")
                stats["errors"] += 1
            finally:
                await browser.close()

        return stats

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección."""
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO RECOLECCIÓN SOMOS PATRIMONIO")
        self.logger.info("=" * 60)

        stats = asyncio.run(self.extract_info())

        if self.records_buffer:
            self.save_to_parquet()

        self.logger.info("=" * 60)
        self.logger.info("RESUMEN")
        self.logger.info(f"  Secciones encontradas: {stats['sections_found']}")
        self.logger.info(f"  Secciones nuevas: {stats['sections_new']}")
        self.logger.info(f"  Errores: {stats['errors']}")
        self.logger.info("=" * 60)

    def setup_logger(self) -> logging.Logger:
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


if __name__ == "__main__":
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Somos_Patrimonio"]
    )
    collector.execute()

    # EDA
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    if os.path.exists(collector.parquet_path):
        df = pl.read_parquet(collector.parquet_path)
        print(f"\n📊 Total de registros: {len(df)}")
        print(f"   Columnas: {df.columns}")

        if "registration_date" in df.columns:
            print(f"\n📅 DISTRIBUCIÓN POR AÑO DE INSCRIPCIÓN:")
            for row in df.group_by("registration_date").len().sort("registration_date").head(10).iter_rows(named=True):
                print(f"   {row['registration_date']}: {row['len']}")
    else:
        print("No existe archivo Parquet.")
