"""Recolector del Boletin Oficial de Defensa (BOD).

Este script automatiza la descarga y extracción de texto de los boletines del BOD publicados
en el portal `publicaciones.defensa.gob.es`. Itera por año sobre las páginas del catálogo,
descarga cada PDF listado en la portada, extrae el texto con PyMuPDF y genera un archivo
Parquet por año con los resultados.

Attributes:
    year (int): Año de arranque para la iteración.
    actual_year (int): Año tope de parada de la recolección.
    path (str): Directorio local donde se almacenan los PDFs y Parquets.
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


def pdf_to_text(pdf_path):
    """Extrae el texto completo de un PDF página a página usando PyMuPDF.

    Args:
        pdf_path (str): Ruta local al archivo PDF.

    Returns:
        str: Texto concatenado de todas las páginas del PDF.
    """
    # Abre el archivo PDF
    doc = fitz.open(pdf_path)
    text_full = ""

    # Itera sobre cada página del PDF
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()

    return text_full

def error_log(error_path, search_url):
    """Registra una URL fallida en un archivo de log.

    Args:
        error_path (str): Ruta del archivo de log (sin extensión `.txt`).
        search_url (str): URL que produjo el error.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def try_pet(search_url, error_path):
    """Ejecuta una petición GET protegida con reintentos ante caídas HTTP.

    Args:
        search_url (str): URL a consultar.
        error_path (str): Ruta del log de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta HTTP y bandera de éxito (1) o fallo (0).
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

def main():
    """Orquestador del scraping del BOD.

    Itera año a año sobre el catálogo Página a Página del BOD, descargando cada PDF listado.
    Por cada PDF extrae el texto con PyMuPDF y lo acumula en una lista de diccionarios
    que al finalizar el año escribe en un archivo Parquet.
    Omite años ya procesados (si existe el Parquet de salida).
    Registra URLs problemáticas en un log de errores.
    """
    # Fetch the web page
    bod_url = "https://publicaciones.defensa.gob.es/bod-acceso-libre/año-de-edición"

    error_path = "/home/adri/scraper/scraper_BODefensa/errors"
    path = '/home/mmg/scraper/scraper_BODefensa/docs'

    year = 2017

    actual_year = 2025
    page = 0
    max_retry = 5

    finished = False

    while not finished:
        finished_year = False

        year += 1
        page = 1
        id_txt = 0
        dict_id_txt = []
        actual_retry = 0

        if os.path.exists(f"{path}/{str(year)}/output.parquet"):
            print(f"Ya existe el archivo {path}/{str(year)}/output.parquet")
        else:
            try:
                if os.path.exists(f"{path}/{str(year)}"):
                    shutil.rmtree(f"{path}/{str(year)}/")
            except Exception as e:
                print(f"Error al borrar el directorio: {e}")
                pass

            while not finished_year:
                print(f"Accediendo a {year} - Pagina {page}")
                print(f"Reintentos: {actual_retry}")
                if actual_retry >= max_retry:
                    print(f"Se ha alcanzado el maximo de reintentos ({max_retry}), pasando de pagina")
                    df = pl.DataFrame(dict_id_txt)
                    df.write_parquet(f"{path}/{year}/output.parquet")
                    finished_year = True
                    continue

                actual_bod_url = f"{bod_url}/{year}/idioma/español/page/{page}.html"
                response, response_find = try_pet(actual_bod_url, error_path)

                if response_find == 0:
                    print(f"No se ha podido acceder a {actual_bod_url}")

                else:
                    
                    if not os.path.exists(f"{path}/{str(year)}/"):
                        os.makedirs(f"{path}/{str(year)}/")
                    
                    if response.status_code == 200:
                        print(f"Accediendo a {actual_bod_url}")
                        # Parse the HTML content
                        soup = BeautifulSoup(response.text, 'html.parser')
                        # Extract specific elements
                        option = soup.find("div", class_="products-list products-list-small row")

                        for link in option.find_all("div", class_="cart_box_but hidden-xs"):
                            
                            pdf_url = link.find('a')['href']
                            print(pdf_url)
                            pdf_name = pdf_url.split("/")[-1]

                            pdf_response, pdf_response_find = try_pet(pdf_url, error_path)
                            if pdf_response_find == 0:
                                print(f"No se ha podido acceder a {pdf_url}")
                            else:
                                if pdf_response.status_code == 200:
                                    if 'bod_20200525_104-al' in pdf_url or 'bod_20210329_1_al' in pdf_url or 'bod_20210326_1_al' in pdf_url or 'bod_20220413_72-al' in pdf_url or '2/0/20230310' in pdf_url:
                                        error_log(error_path, pdf_url)
                                    elif '.pdf' in pdf_name:
                                        print(f"Accediendo a {pdf_url}")
                                        print(f"{path}/{str(year)}/{pdf_name}")
                                        if not os.path.exists(f"{path}/{str(year)}/{pdf_name}"):
                                            with open(f"{path}/{str(year)}/{pdf_name}", "wb") as file:
                                                file.write(pdf_response.content)

                                            text = pdf_to_text(f"{path}/{str(year)}/{pdf_name}")
                                            dict_id_txt.append({"id": id_txt, "text": text, "anio": year, "url": pdf_url})
                                            id_txt += 1
                                        else:
                                            print("Reintentando acceso al PDF")
                                            actual_retry += 1
                                else:
                                    print(f"No se ha podido acceder a {pdf_url}")
                    page += 1
                    print(f"Pagina {page}")
                if year == actual_year + 1:
                    finished = True


        # data = response.text

        # # Parse the HTML content
        # soup = BeautifulSoup(data, 'html.parser')




                            # df = pl.DataFrame(dict_id_txt)

                            # df.write_parquet(f"{path}/{org}/output.parquet")
                            # finished = True

if __name__ == "__main__":
    main()