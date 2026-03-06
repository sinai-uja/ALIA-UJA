"""Método de recolección para la Agenda Urbana Española.

Este módulo implementa un recolector que obtiene documentos PDF
del portal de la Agenda Urbana Española y la transferencia de
conocimiento urbanístico.

El método:
    - Explora el sitio web usando crawl4ai
    - Descarga PDFs encontrados
    - Extrae texto de los documentos
    - Genera dataset en formato Parquet

Example:
    Ejecución básica::

        python crawler_legal_agenda_urbana_espana.py

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
ROOT_URL = "https://www.aue.gob.es/transferencia-de-conocimiento"
DATASET_NAME = "Agenda_Urbana_Espana"


class AgendaUrbanaCrawler(CrawlerBase):
    """Recolector especializado para la Agenda Urbana Española.

    Extiende CrawlerBase para explorar el portal de la AUE
    y descargar documentos relacionados con urbanismo.

    Attributes:
        folders (list[str]): Carpetas para organizar el dataset.
        blocked_domains (list[str]): Dominios a excluir de la exploración.

    Example:
        >>> recolector = AgendaUrbanaCrawler("config.yaml")
        >>> asyncio.run(recolector.run())
    """

    def __init__(self, config_path: str) -> None:
        """Inicializa el recolector.

        Args:
            config_path (str): Ruta al archivo YAML de configuración.
        """
        crawler_config = {
            "blocked_internal_domains": [
                "transportes.gob.es",
                "navarra.es",
                "dipucordoba.es",
                "fundacionconama.org",
                "blogs.upm.es"
            ],
            "excluded_markdown_tags": ["header", "footer"],
            "max_depth": 2,
            "include_external_links": True
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

    crawler = AgendaUrbanaCrawler("config.yaml")
    asyncio.run(crawler.run())

    # EDA
    print("\n" + "=" * 80)
    print("ANÁLISIS EXPLORATORIO DEL DATASET")
    print("=" * 80)

    if os.path.exists(crawler.parquet_path):
        df = pl.read_parquet(crawler.parquet_path)
        print(f"\n📊 Total de registros: {len(df)}")
        print(f"   Columnas: {df.columns}")

        if "parent_url" in df.columns:
            print(f"\n📂 URLs PADRE MÁS COMUNES:")
            for row in df.group_by("parent_url").len().sort("len", descending=True).head(5).iter_rows(named=True):
                print(f"   {row['parent_url'][:60]}: {row['len']}")
    else:
        print("No existe archivo Parquet.")
