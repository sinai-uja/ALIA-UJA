"""Descargador de códigos jurídicos del BOE relacionados con patrimonio cultural.

Este módulo descarga una selección fija de PDFs de la Biblioteca Jurídica
Digital del BOE (Boletín Oficial del Estado) correspondientes a códigos
legislativos sobre patrimonio, museos, archivos, bibliotecas, cinematografía
y artes audiovisuales, y genera un CSV e índice Parquet con los resultados.

Los documentos objetivo son:
    - Patrimonio Cultural de las Administraciones Públicas
    - Código de Museos
    - Código de Archivos y Patrimonio Documental
    - Código de Legislación Bibliotecaria
    - Código de Legislación Bibliotecaria Autonómica
    - Código de Cinematografía y Artes Audiovisuales
    - Código del Patrimonio Audiovisual
    - Código de Derecho Cultural
    - Patrimonio de las Administraciones Públicas

Example:
    Ejecución básica::

        python scraper_boe_codigos.py

    Esto descargará los PDFs en la carpeta ``pdfs/``, generará el CSV
    ``BOE_Patrimonio.csv`` y su equivalente Parquet.

Attributes:
    OUTPUT_DIR (str): Directorio donde se guardan los PDFs descargados.
    CSV_OUTPUT (str): Nombre del archivo CSV de salida.
    HEADERS (dict): Cabeceras HTTP para imitar un navegador real.
    PDFS (list[tuple]): Lista de pares (título descriptivo, URL de descarga).

Note:
    Los documentos son de acceso público a través de la Biblioteca Jurídica
    Digital del BOE.
    URL: https://www.boe.es/biblioteca_juridica/
"""

import os
import csv
import time
import requests
import polars as pl

# ─── Configuración ────────────────────────────────────────────────────────────

# Directorio donde se guardarán los PDFs descargados
OUTPUT_DIR = "pdfs"

# Nombre del CSV resultante
CSV_OUTPUT = "BOE_Patrimonio.csv"

# Cabeceras HTTP para imitar un navegador y evitar bloqueos
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Lista de PDFs a descargar: (título descriptivo, URL de descarga)
PDFS = [
    (
        "Patrimonio Cultural de las Administraciones Públicas",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=175_Patrimonio_Cultural_de_las_Administraciones_Publicas.pdf",
    ),
    (
        "Código de Museos",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=177_Codigo_de_Museos__.pdf",
    ),
    (
        "Código de Archivos y Patrimonio Documental",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=092_Codigo_de_Archivos_y_Patrimonio_Documental.pdf",
    ),
    (
        "Código de Legislación Bibliotecaria",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=024_Codigo_de_Legislacion_Bibliotecaria.pdf",
    ),
    (
        "Código de Legislación Bibliotecaria Autonómica",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=134_Codigo_de_Legislacion_Bibliotecaria_Autonomica.pdf",
    ),
    (
        "Código de Cinematografía y Artes Audiovisuales",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=220_Codigo_de_Cinematografia_y_Artes_Audiovisuales.pdf",
    ),
    (
        "Código del Patrimonio Audiovisual",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=533_Codigo_del_Patrimonio_Audiovisual_.pdf",
    ),
    (
        "Código de Derecho Cultural",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=428_Codigo_de_Derecho_Cultural.pdf",
    ),
    (
        "Patrimonio de las Administraciones Públicas",
        "https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=170_Patrimonio_de_las_Administraciones_Publicas.pdf",
    ),
]

# ─── Funciones ────────────────────────────────────────────────────────────────


def get_filename_from_url(url: str) -> str:
    """Extrae el nombre del fichero a partir del parámetro ``fich`` de la URL.

    La URL del BOE sigue el formato:
    ``...abrir_pdf.php?fich=NOMBRE.pdf``

    Args:
        url: URL completa de descarga del PDF en la Biblioteca Jurídica del BOE.

    Returns:
        Nombre del fichero PDF tal como aparece en el parámetro ``fich``.
    """
    return url.split("fich=")[-1]


def download_pdf(url: str, dest_path: str) -> bool:
    """Descarga un PDF desde una URL y lo guarda en la ruta indicada.

    Omite la descarga si el archivo ya existe en disco. Incluye una
    verificación básica del Content-Type para confirmar que el recurso
    es realmente un PDF.

    Args:
        url: URL directa del PDF a descargar.
        dest_path: Ruta completa (incluido nombre de archivo) donde guardar el PDF.

    Returns:
        ``True`` si la descarga fue exitosa o el archivo ya existía,
        ``False`` si se produjo un error de red o HTTP.
    """
    try:
        print(f"  Descargando: {os.path.basename(dest_path)} ...")
        response = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        response.raise_for_status()

        # Verificar que el contenido es realmente un PDF
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            print(f"  ⚠ Advertencia: Content-Type inesperado: {content_type}")

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        size_kb = os.path.getsize(dest_path) / 1024
        print(f"  ✓ Guardado ({size_kb:.1f} KB): {dest_path}")
        return True

    except requests.RequestException as e:
        print(f"  ✗ Error al descargar {url}: {e}")
        return False


def main():
    """Ejecuta el proceso completo de descarga y generación de CSV y Parquet.

    Recorre la lista ``PDFS``, descarga cada archivo (omitiendo los ya
    existentes), construye el CSV con los metadatos y lo convierte a Parquet.
    Incluye una pausa de 1 segundo entre descargas para no sobrecargar el
    servidor del BOE.
    """
    # Crear directorio de salida si no existe
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Directorio de descarga: {os.path.abspath(OUTPUT_DIR)}\n")

    rows = []

    for titulo, url in PDFS:
        filename = get_filename_from_url(url)
        dest_path = os.path.join(OUTPUT_DIR, filename)

        print(f"[{titulo}]")

        # Si ya existe el fichero, no lo vuelve a descargar
        if os.path.exists(dest_path):
            print(f"  → Ya existe, se omite la descarga: {filename}")
            success = True
        else:
            success = download_pdf(url, dest_path)
            time.sleep(1)  # Pausa entre descargas para no sobrecargar el servidor

        if success:
            rows.append({"Id": os.path.splitext(filename)[0], "url": url, "text": ""})
        print()

    # Escribir el CSV
    csv_path = os.path.join(OUTPUT_DIR, CSV_OUTPUT)
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["Id", "url", "text"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV generado con {len(rows)} entradas: {os.path.abspath(csv_path)}")

    # Convertir el CSV a Parquet con Polars
    parquet_path = os.path.splitext(csv_path)[0] + ".parquet"
    df = pl.read_csv(csv_path, encoding="utf8")
    df.write_parquet(parquet_path)
    print(f"Parquet generado: {os.path.abspath(parquet_path)}")


if __name__ == "__main__":
    main()
