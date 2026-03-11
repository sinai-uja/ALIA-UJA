"""Recolector de capítulos en PDF de SECOMCYC.

Este módulo descarga y extrae el texto de los capítulos del libro
de la Sociedad Española de Cirugía Oral, Maxilofacial y de Cabeza
y Cuello (SECOMCYC) publicado en formato PDF en su sitio web oficial.

El proceso consiste en iterar sobre los nombres de archivo de los
capítulos (``cap01.pdf`` a ``cap61.pdf``, más ``autores.pdf`` e
``indice.pdf``), descargarlos desde la URL base de la sociedad,
extraer su texto con PyMuPDF (fitz) y serializar los registros en
un archivo Parquet.

Example:
    Ejecución básica::

        python scraper_SECOMCYC.py

    Esto descargará todos los capítulos disponibles, extraerá su
    texto y generará el archivo ``output.parquet`` en la ruta
    configurada.

Attributes:
    OUTPUT_FOLDER (Path): Ruta donde se guardan los PDFs descargados.
    PARQUET_OUTPUT (Path): Ruta del archivo Parquet de salida.
    BASE_URL (str): URL base desde la que se descargan los PDFs.
    pdf_files (list[str]): Lista de nombres de archivo a descargar.
    headers (dict): Cabeceras HTTP para las peticiones de descarga.

Note:
    Los datos proceden de la publicación oficial de la SECOMCYC.
    URL: http://www.secomcyc.org
"""

import os
import requests
import time
import pandas as pd
import fitz
from pathlib import Path


# ------------------------------
# FUNCION PARA EXTRAER TEXTO
# ------------------------------
def pdf_to_text(pdf_path: Path) -> str:
    """Extrae el texto completo de un archivo PDF.

    Abre el PDF con PyMuPDF e itera sobre todas sus páginas
    concatenando el texto plano extraído de cada una.

    Args:
        pdf_path: Ruta al archivo PDF del que extraer el texto.

    Returns:
        String con el texto completo del PDF.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

# ------------------------------
# CONFIGURACIÓN DE RUTAS
# ------------------------------
BASE_DIR = Path(__file__).parent / "SECOMCYC"
OUTPUT_FOLDER = BASE_DIR / "docs"
PARQUET_OUTPUT = BASE_DIR / "output.parquet"
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://www.secomcyc.org//wp-content/uploads/2014/01"

pdf_files = [f"cap{str(i).zfill(2)}.pdf" for i in range(1, 62)]
pdf_files += ["autores.pdf", "indice.pdf"]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}

# ------------------------------
# DESCARGA + EXTRACCION DE TEXTO
# ------------------------------
records = []
counter = 0

for pdf in pdf_files:
    url = f"{BASE_URL}/{pdf}"
    local_path = OUTPUT_FOLDER / pdf
    print(f"Descargando {pdf}...")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        with open(local_path, 'wb') as f:
            f.write(response.content)
        print(f"✔ Guardado en {local_path}")

        # EXTRAER TEXTO
        texto = pdf_to_text(local_path)

        # GUARDAR REGISTRO
        records.append({
            "id": counter,
            "url": url,
            "capitulo": pdf.replace(".pdf", ""),
            "text": texto
        })
        counter += 1

    except requests.exceptions.RequestException as e:
        print(f"❌ Error al descargar {pdf}: {e}")

    time.sleep(1)

# ------------------------------
# GUARDAR A PARQUET
# ------------------------------
df = pd.DataFrame(records)
df["seccion_clinica"] = "Cirugia Oral y Maxilofacial"
df.to_parquet(PARQUET_OUTPUT, index=False)
print(f"✅ Descarga completada y datos guardados en {PARQUET_OUTPUT}")
