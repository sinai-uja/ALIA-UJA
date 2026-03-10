"""Método de recolección del Ministerio de Transición Ecológica.

Este módulo implementa un recolector que obtiene documentos PDF
del portal del Ministerio para la Transición Ecológica y el
Reto Demográfico.

El método:
    - Explora el sitio web usando crawl4ai
    - Descarga PDFs de normativa ambiental
    - Extrae texto de los documentos
    - Genera dataset en formato Parquet

Example:
    Ejecución básica::

        python crawler_legal_ministerio_transicion_ecologica.py

    Esto explorará el sitio y generará output.parquet.

Attributes:
    ROOT_URL (str): URL raíz para la exploración.
    DATASET_NAME (str): Nombre del dataset resultante.

Note:
    Hereda de CrawlerBase para funcionalidad de exploración.
"""

import asyncio
import os

import nest_asyncio
import polars as pl

# Importar CrawlerBase del módulo padre
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from CrawlerBase import CrawlerBase


# Configuración
ROOT_URL = "https://www.miteco.gob.es/"
DATASET_NAME = "Ministerio_Transicion_Ecologica"


class MITECOCrawler(CrawlerBase):
    """Recolector para el Ministerio de Transición Ecológica.

    Extiende CrawlerBase para explorar el portal del MITECO
    y descargar documentos de normativa ambiental.

    Attributes:
        folders (list[str]): Carpetas para organizar el dataset.

    Example:
        >>> recolector = MITECOCrawler("config.yaml")
        >>> asyncio.run(recolector.run())
    """

    def __init__(self, config_path: str) -> None:
        """Inicializa el recolector.

        Args:
            config_path (str): Ruta al archivo YAML de configuración.
        """
        crawler_config = {
            "allowed_internal_domains": ["miteco.gob.es"],
            "excluded_markdown_tags": ["header", "footer", "nav"],
            "max_depth": 3,
            "include_external_links": False
        }

        super().__init__(
            config_path=config_path,
            folders=["ALIA", DATASET_NAME],
            root_url=ROOT_URL,
            crawler_config=crawler_config
        )

    async def run(self) -> None:
        """Ejecuta el proceso de recolección."""
        await self.execute()


if __name__ == "__main__":
    nest_asyncio.apply()

    crawler = MITECOCrawler("config.yaml")
    asyncio.run(crawler.run())

    # EDA
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    if os.path.exists(crawler.parquet_path):
        df = pl.read_parquet(crawler.parquet_path)
        print(f"\n📊 Total de registros: {len(df)}")
        print(f"   Columnas: {df.columns}")
    else:
        print("No existe archivo Parquet.")
