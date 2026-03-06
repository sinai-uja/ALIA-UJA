"""Método de recolección del Código Técnico de la Edificación.

Este módulo implementa un recolector que obtiene documentos PDF
del portal del Código Técnico de la Edificación del Ministerio.

El método:
    - Explora el sitio web usando crawl4ai
    - Descarga PDFs de normativa técnica
    - Extrae texto de los documentos
    - Genera dataset en formato Parquet

Example:
    Ejecución básica::

        python crawler_legal_codigo_tecnico_edificacion.py

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
ROOT_URL = "https://www.codigotecnico.org/"
DATASET_NAME = "Codigo_Tecnico_Edificacion"


class CodigoTecnicoCrawler(CrawlerBase):
    """Recolector especializado para el Código Técnico de Edificación.

    Extiende CrawlerBase para explorar el portal del CTE
    y descargar documentos de normativa técnica.

    Attributes:
        folders (list[str]): Carpetas para organizar el dataset.

    Example:
        >>> recolector = CodigoTecnicoCrawler("config.yaml")
        >>> asyncio.run(recolector.run())
    """

    def __init__(self, config_path: str) -> None:
        """Inicializa el recolector.

        Args:
            config_path (str): Ruta al archivo YAML de configuración.
        """
        crawler_config = {
            "allowed_internal_domains": ["codigotecnico.org"],
            "excluded_markdown_tags": ["header", "footer", "nav"],
            "max_depth": 5,
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

    crawler = CodigoTecnicoCrawler("config.yaml")
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
