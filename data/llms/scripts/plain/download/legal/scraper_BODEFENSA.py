"""Recolector de publicaciones del Boletín Oficial de Defensa (BOD).

Este módulo descarga y extrae el texto de los documentos PDF
publicados en el Boletín Oficial de Defensa (BOD) del Ministerio
de Defensa de España, paginando por año desde 2018 hasta el
año en curso.

El proceso navega las páginas de resultados por año e idioma,
descarga cada PDF encontrado, extrae su texto con PyMuPDF (fitz)
y almacena todos los registros en archivos Parquet individuales
por año y en un Parquet global consolidado.

Example:
    Ejecución básica::

        python scraper_BODEFENSA.py

    Esto descargará todos los PDFs disponibles en el BOD desde
    2018 hasta 2025 y generará los archivos Parquet en la ruta
    configurada.

Note:
    Los datos son de acceso público a través del portal de
    publicaciones del Ministerio de Defensa.
    URL: https://publicaciones.defensa.gob.es/bod-acceso-libre
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
import shutil
from pathlib import Path


# Rutas relativas al directorio donde se ejecuta el script
BASE_DIR = Path(__file__).parent / "BODEFENSA"
DOCS_DIR = BASE_DIR / "docs"
ERROR_PATH = BASE_DIR / "errors"


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
    try:
        response = requests.get(search_url, stream=True)
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
                response = requests.get(search_url)
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

def main() -> None:
    """Función principal: descarga PDFs del BOD y guarda los datos.

    Itera por año (desde 2018 hasta el año en curso), pagina por
    los resultados del Boletín Oficial de Defensa, descarga cada
    PDF, extrae su texto y guarda los registros en Parquets
    individuales por año y en un Parquet global consolidado.

    Raises:
        Exception: Si se produce un error al borrar un directorio
            existente o al guardar el Parquet.
    """
    # Crear directorios si no existen
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    bod_url = "https://publicaciones.defensa.gob.es/bod-acceso-libre/año-de-edición"

    year = 2017
    actual_year = 2025
    page = 0
    max_retry = 5

    finished = False
    dict_id_txt_global = []
    contador = 0

    while not finished:
        finished_year = False

        year += 1
        page = 1
        id_txt = 0
        dict_id_txt = []
        actual_retry = 0

        year_dir = DOCS_DIR / str(year)
        year_parquet = year_dir / "output.parquet"

        if year_parquet.exists():
            print(f"Ya existe el archivo {year_parquet}")
        else:
            try:
                if year_dir.exists():
                    shutil.rmtree(year_dir)
            except Exception as e:
                print(f"Error al borrar el directorio: {e}")
                pass

            while not finished_year:
                print(f"Accediendo a {year} - Pagina {page}")
                print(f"Reintentos: {actual_retry}")
                if actual_retry >= max_retry:
                    print(f"Se ha alcanzado el maximo de reintentos ({max_retry}), pasando de pagina")
                    df = pl.DataFrame(dict_id_txt)
                    df.write_parquet(year_parquet)
                    finished_year = True
                    continue

                actual_bod_url = f"{bod_url}/{year}/idioma/español/page/{page}.html"
                response, response_find = try_pet(actual_bod_url, ERROR_PATH)

                if response_find == 0:
                    print(f"No se ha podido acceder a {actual_bod_url}")

                else:
                    year_dir.mkdir(parents=True, exist_ok=True)

                    if response.status_code == 200:
                        print(f"Accediendo a {actual_bod_url}")
                        soup = BeautifulSoup(response.text, 'html.parser')
                        option = soup.find("div", class_="products-list products-list-small row")

                        if option is None:
                            print(f"No se encontró la sección de productos en {actual_bod_url}")
                            if dict_id_txt:
                                df = pl.DataFrame(dict_id_txt)
                                df.write_parquet(year_parquet)
                                print(f"Guardado el archivo {year_parquet} con los datos recolectados hasta ahora.")
                            finished_year = True

                            print(f"El year es: {year} el actual year es {actual_year}")
                            if year + 1 > actual_year:
                                finished = True
                            continue

                        for link in option.find_all("div", class_="cart_box_but hidden-xs"):
                            pdf_url = link.find('a')['href']
                            print(pdf_url)
                            pdf_name = pdf_url.split("/")[-1]

                            pdf_response, pdf_response_find = try_pet(pdf_url, ERROR_PATH)
                            if pdf_response_find == 0:
                                print(f"No se ha podido acceder a {pdf_url}")
                            else:
                                if pdf_response.status_code == 200:
                                    if 'bod_20200525_104-al' in pdf_url or 'bod_20210329_1_al' in pdf_url or 'bod_20210326_1_al' in pdf_url or 'bod_20220413_72-al' in pdf_url or '2/0/20230310' in pdf_url:
                                        error_log(ERROR_PATH, pdf_url)
                                    elif '.pdf' in pdf_name:
                                        pdf_path = year_dir / pdf_name
                                        print(f"Accediendo a {pdf_url}")
                                        print(f"{pdf_path}")
                                        if not pdf_path.exists():
                                            with open(pdf_path, "wb") as file:
                                                file.write(pdf_response.content)
                                            text = pdf_to_text(pdf_path)
                                            dict_id_txt.append({"id": id_txt, "text": text, "anio": year, "url": pdf_url})
                                            dict_id_txt_global.append({"id": contador, "text": text, "anio": year, "url": pdf_url})
                                            id_txt += 1
                                            contador += 1
                                        else:
                                            print("Reintentando acceso al PDF")
                                            actual_retry += 1
                                else:
                                    print(f"No se ha podido acceder a {pdf_url}")
                    page += 1
                    print(f"Pagina {page}")

    df = pl.DataFrame(dict_id_txt_global)
    df.write_parquet(DOCS_DIR / "output.parquet")
    print("Parquet exitosamente guardado")

if __name__ == "__main__":
    main()