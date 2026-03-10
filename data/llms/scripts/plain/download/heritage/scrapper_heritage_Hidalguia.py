"""Descargador de PDFs de la Revista Hidalguía.

Este módulo descarga los números de la Revista Hidalguía de forma secuencial,
accediendo a cada número mediante un formulario de descarga en la web de la
revista, extrayendo el texto de los PDFs descargados y generando un CSV e
índice Parquet con los resultados.

La Revista Hidalguía contiene:
    - Estudios sobre genealogía, heráldica y nobleza española
    - Publicaciones especializadas en historia nobiliaria

Example:
    Ejecución básica::

        python scrapper_heritage_Hidalguia.py

    Esto recorrerá los números del 1 al 399, descargando los PDFs disponibles
    en la carpeta ``pdfs/`` y generando ``output.csv`` y ``output.parquet``.

Attributes:
    BASE_URL (str): Patrón de URL de cada número de la revista.
    OUTPUT_FOLDER (str): Carpeta de destino para los PDFs.
    CSV_FILE (str): Nombre del archivo CSV de salida.
    PARQUET_FILE (str): Nombre del archivo Parquet de salida.
    HEADERS (dict): Cabeceras HTTP para imitar un navegador real.

Note:
    Los PDFs se obtienen enviando un formulario POST con parámetros ocultos
    a la web de la revista.
    URL: https://www.revistahidalguia.es/
"""

import os
import time
import csv
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import PyPDF2
import polars as pl

BASE_URL = "https://www.revistahidalguia.es/producto/revista-hidalguia-numero-{}"
OUTPUT_FOLDER = "pdfs"
CSV_FILE = "output.csv"
PARQUET_FILE = "output.parquet"

# Crear carpeta para PDFs
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PDFDownloader/1.0; +https://example.com)"
}


def descargar_pdf(num: int, action_url: str, data: dict) -> str | None:
    """Envía el formulario POST para descargar el PDF de un número de la revista.

    Comprueba si el PDF ya existe en disco antes de descargarlo. Verifica que
    la respuesta sea de tipo ``application/pdf`` antes de guardarla.

    Args:
        num: Número de la revista que se intenta descargar.
        action_url: URL de acción del formulario de descarga.
        data: Diccionario con los parámetros ocultos del formulario POST.

    Returns:
        Ruta local del PDF descargado si la descarga fue exitosa,
        ``None`` en caso contrario.
    """
    nombre_archivo = f"hidalguia_{num}.pdf"
    ruta_destino = os.path.join(OUTPUT_FOLDER, nombre_archivo)

    if os.path.exists(ruta_destino):
        print(f" Ya existe: {nombre_archivo}")
        return ruta_destino

    try:
        r = requests.post(action_url, headers=HEADERS, data=data, timeout=30)
        if r.status_code == 200 and "application/pdf" in r.headers.get("content-type", ""):
            with open(ruta_destino, "wb") as f:
                f.write(r.content)
            print(f" Descargado: {nombre_archivo}")
            return ruta_destino
        else:
            print(f" No se obtuvo un PDF válido (status {r.status_code}) en número {num}")
    except Exception as e:
        print(f" Error descargando número {num}: {e}")
    return None


def extraer_texto_pdf(pdf_path: str) -> str:
    """Extrae el texto embebido de un PDF usando PyPDF2.

    Args:
        pdf_path: Ruta al archivo PDF del que extraer el texto.

    Returns:
        Texto extraído del PDF, o cadena vacía si ocurrió un error.
    """
    texto_total = ""
    try:
        with open(pdf_path, "rb") as f:
            lector = PyPDF2.PdfReader(f)
            for pagina in lector.pages:
                texto_total += pagina.extract_text() or ""
        return texto_total.strip()
    except Exception as e:
        print(f" Error leyendo PDF {pdf_path}: {e}")
        return ""


def buscar_y_descargar_pdf(num: int, csv_writer: csv.DictWriter) -> None:
    """Accede a la página de un número de la revista, extrae el formulario de
    descarga, descarga el PDF y escribe el registro al CSV.

    Args:
        num: Número de la revista a procesar.
        csv_writer: Escritor de CSV donde añadir el registro del número procesado.
    """
    url = BASE_URL.format(num)
    print(f"\n Revisando número {num}: {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f" Página no encontrada ({resp.status_code})")
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form", {"class": "somdn-download-form"})
        if not form:
            print(" No se encontró formulario de descarga en esta página.")
            return

        action_url = form.get("action") or url
        action_url = urljoin(url, action_url)

        data = {inp.get("name"): inp.get("value", "") for inp in form.find_all("input", {"type": "hidden"}) if inp.get("name")}
        if not data:
            print(" Formulario sin datos, no se puede descargar.")
            return

        print(f" Enviando POST a {action_url} con {len(data)} parámetros...")
        ruta_pdf = descargar_pdf(num, action_url, data)

        if ruta_pdf:
            texto = extraer_texto_pdf(ruta_pdf)
            csv_writer.writerow({
                "id": os.path.splitext(os.path.basename(ruta_pdf))[0],
                "url": url,
                "text": texto
            })
            print(f" Texto extraído y guardado en CSV: hidalguia_{num}")
        else:
            print(f" No se descargó el PDF {num}")

    except Exception as e:
        print(f" Error procesando la página {url}: {e}")


def main():
    """Ejecuta el proceso completo de descarga y generación de CSV y Parquet.

    Recorre los números del 1 al 399 de la revista, descarga cada PDF
    disponible, extrae su texto y escribe los resultados en ``output.csv``.
    Al finalizar, convierte el CSV a formato Parquet con Polars. Incluye
    una pausa de 1 segundo entre peticiones para no sobrecargar el servidor.
    """
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["id", "url", "text"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for i in range(1, 400):
            buscar_y_descargar_pdf(i, writer)
            time.sleep(1)  # Pausa para no sobrecargar el servidor

    print(f"\n CSV generado: '{CSV_FILE}'")

    # Convertir CSV a Parquet con Polars
    try:
        df = pl.read_csv(CSV_FILE)
        df.write_parquet(PARQUET_FILE)
        print(f" CSV convertido a Parquet: '{PARQUET_FILE}'")
    except Exception as e:
        print(f" Error convirtiendo CSV a Parquet: {e}")


if __name__ == "__main__":
    main()