"""Recolector de contenidos de la Agenda 2030 de Naciones Unidas.

Este módulo extrae los textos descriptivos de cada uno de los 17
Objetivos de Desarrollo Sostenible (ODS) publicados por la ONU en
la web de la Agenda 2030, genera un PDF por objetivo y serializa
los metadatos en un archivo Parquet.

El proceso consiste en acceder a la página principal de la Agenda
2030, extraer los enlaces a cada ODS, descargar su contenido
textual con requests y BeautifulSoup, generar un PDF con reportlab
y almacenar los registros en un DataFrame de polars.

Example:
    Ejecución básica::

        python scraper_Agenda_2030.py

    Esto accederá a la web de la Agenda 2030, extraerá el texto de
    los 17 ODS y generará los PDFs y el archivo ``output.parquet``
    en la ruta configurada.

Note:
    Los datos son de acceso público a través del portal de la ONU.
    URL: https://www.un.org/sustainabledevelopment/es/
"""

from bs4 import BeautifulSoup
import requests
import urllib.parse
import fitz
import os
from requests.exceptions import ChunkedEncodingError
import time
import polars as pl
import sys
from multiprocessing import Pool, cpu_count
import re
from pathlib import Path
from requests.compat import urljoin
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import LETTER


# Rutas relativas al directorio donde se ejecuta el script
BASE_DIR = Path(__file__).parent / "Agenda_2030"
DOCS_DIR = BASE_DIR / "docs"
ERROR_PATH = BASE_DIR / "errors"


def error_log(error_path: Path, search_url: str) -> None:
    """Registra una URL fallida en el fichero de errores.

    Args:
        error_path: Ruta base del fichero de errores (sin extensión).
        search_url: URL que no pudo ser accedida correctamente.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

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

def try_pet(search_url: str, error_path: Path) -> tuple:
    """Realiza una petición HTTP con reintentos ante fallos.

    Intenta acceder a la URL dada y, si la respuesta no es exitosa,
    reintenta hasta 5 veces con espera incremental. Los fallos
    definitivos se registran en el fichero de errores.

    Args:
        search_url: URL a la que realizar la petición GET.
        error_path: Ruta base del fichero de errores (sin extensión).

    Returns:
        Tupla ``(response, response_find)`` donde ``response`` es el
        objeto Response de requests (o None si falló) y
        ``response_find`` es 1 si se obtuvo respuesta o 0 si no.
    """
    i = 0
    response_find = 0
    response = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(search_url, headers=headers, stream=True)
        if response and response.status_code == 200:
            response_find = 1
            return response, response_find
        elif response.status_code == 404:
            response_find = 1
            return response, response_find
        else:
            find = False
            for i in range(5):
                print(f"No se pudo acceder a {search_url}: reintentamos")
                time.sleep(i+1)
                response = requests.get(search_url, headers=headers)
                if response and response.status_code == 200:
                    print("Se ha aceptado el reintento de conexion")
                    find = True
                    break
            if find == False:
                error_log(error_path, search_url)
            response_find = 1
            return response, response_find
    except ChunkedEncodingError as e:
        print(f"Error en la transferencia de datos.")
        error_log(error_path, search_url)
        response_find = 0
        response = None
        return response, response_find
    except requests.exceptions.RequestException as e:
        print(f"Intento {i+1}: error al acceder a {search_url}: {e}")
        error_log(error_path, search_url)
        response_find = 0
        response = None
        return response, response_find


def exportar_pdf(nombre_archivo: Path, titulo: str, parrafos: list, lista_datos: list = None) -> None:
    """Crea un PDF con un título, varios párrafos y (opcionalmente) una lista con viñetas.

    Args:
        nombre_archivo: Ruta completa donde guardar el PDF.
        titulo: Título principal del documento.
        parrafos: Lista de párrafos (strings) a incluir en el cuerpo.
        lista_datos: Lista con elementos tipo bullet point. Defaults a None.
    """
    doc = SimpleDocTemplate(str(nombre_archivo), pagesize=LETTER,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=72)

    styles = getSampleStyleSheet()
    story = []

    # Título
    story.append(Paragraph(titulo, styles['Title']))
    story.append(Spacer(1, 12))

    # Párrafos
    for parrafo in parrafos:
        story.append(Paragraph(parrafo, styles['Normal']))
        story.append(Spacer(1, 12))

    # Lista (si existe)
    if lista_datos:
        items = [ListItem(Paragraph(item, styles['Normal'])) for item in lista_datos]
        story.append(ListFlowable(items, bulletType='bullet'))
        story.append(Spacer(1, 12))

    doc.build(story)


def main() -> None:
    """Función principal: extrae y guarda los contenidos de la Agenda 2030.

    Accede a la página principal de los ODS de la ONU, obtiene los
    enlaces a cada uno de los 17 Objetivos de Desarrollo Sostenible,
    extrae su contenido textual, genera un PDF por objetivo y
    almacena los metadatos en un archivo Parquet.

    Raises:
        Exception: Si se produce un error no controlado al procesar
            la página o al guardar el Parquet.
    """

    # Crear directorios si no existen
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    base_url = "https://www.un.org"
    url = "https://www.un.org/sustainabledevelopment/es/"

    diccionario = []
    finished = False

    while not finished:
        response, response_find = try_pet(url, ERROR_PATH)

        if response_find == 0:
            print(f"No se ha podido acceder a {url}")

        else:
            if response.status_code == 404:
                print(f"No se han encontrado más documentos en la página")
                continue

            else:
                if response.status_code == 200:

                    print(f"Accediendo a página {url}")
                    soup = BeautifulSoup(response.text, 'html.parser')

                    try:
                        print("Estamos dentro")
                        # Buscar todos los <a> dentro de los flip-box
                        flip_links = soup.select("div.flip-box-back-inner a[href]")

                        # Extraer los enlaces (href)
                        urls = [a['href'] for a in flip_links]

                        # Agregar el dominio si es relativo
                        full_urls = [u if u.startswith("http") else base_url + u for u in urls][:17]
                        for i, u in enumerate(full_urls):
                            print(f"{i}:{u}")
                        finished = True

                        if not full_urls:
                            finished = True
                            print(f"No se encontraron enlaces en la página {url}. Finalizando.")
                            continue

                        for i, url in enumerate(full_urls):
                            i += 1
                            print(f"Enlace: {url}")
                            response_doc, response_find_doc = try_pet(url, ERROR_PATH)

                            if response_find_doc == 0:
                                print(f"No se ha podido acceder a {url}")

                            else:
                                if response_doc.status_code == 404:
                                    print(f"No se han encontrado documentos")
                                    continue
                                else:
                                    if response.status_code == 200:

                                        print(f"Accediendo a página {url}")
                                        soup_doc = BeautifulSoup(response_doc.text, 'html.parser')

                                        p_tags = soup_doc.select("div.fusion-text p")
                                        parrafos = [p.get_text(strip=True) for p in p_tags if p is not None]
                                        texto_url = "\n\n".join(parrafos)
                                        print("HECHOS los parrafos")

                                        title = soup_doc.find('h1', class_='entry-title').get_text(strip=True)
                                        print("HECHO el título")

                                        print("HECHOS los apartados")

                                        contenido = texto_url.split("\n\n")
                                        nombre_archivo = DOCS_DIR / f"Objetivo{i}.pdf"

                                        exportar_pdf(nombre_archivo, title, contenido)

                                        print(f"Guardando en {nombre_archivo}")
                                        if nombre_archivo.exists():
                                            print(f"El archivo {nombre_archivo} ya existe")
                                        print("Archivo guardado")

                                        try:
                                            diccionario.append({"id": i, "txt": " ", "url": url, "titulo": title})
                                            print({
                                                "id": i,
                                                "txt": "EL TEXTO",
                                                "url": url,
                                                "titulo": title,
                                            })
                                        except Exception as e:
                                            print(f"Error al añadir el texto a la lista: {e}")
                                            continue
                    except Exception as e:
                        print(f"Error al extraer los elementos de la página: {e}")
                        continue

    try:
        df = pl.DataFrame(diccionario)
        df.write_parquet(BASE_DIR / "output.parquet")

    except Exception as e:
        print(f"Error al guardar el parquet: {e}")


if __name__ == "__main__":
    main()