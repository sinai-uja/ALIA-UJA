"""Recolector del Boletin Oficial del Registro Mercantil (BORME).

Este script automatiza la descarga y extracción de texto de los PDFs del BORME publicados
en `boe.es/borme`. Itera día a día sobre el sumario de cada fecha, extrae los enlaces PDF
del bloque `sumario`, descarga cada PDF, extrae el texto con PyMuPDF y los guarda en un
archivo Parquet por día.

Attributes:
    year (int): Año de arranque.
    month (int): Mes de arranque.
    day (int): Día de arranque.
    actual_year (int): Año de parada.
    actual_month (int): Mes de parada.
    actual_day (int): Día de parada.
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
from pypdf import PdfMerger

def pdf_to_text(pdf_path):
    """Extrae el texto completo de un PDF página a página usando PyMuPDF.

    Args:
        pdf_path (str): Ruta local al archivo PDF.

    Returns:
        str: Texto concatenado de todas las páginas.
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
    """Orquestador del scraping del BORME.

    Itera día a día sobre el portal BORME accediendo al sumario de cada fecha.
    Por cada PDF encontrado en el bloque `div.sumario`, descarga el binario, extrae el texto
    con PyMuPDF y acumula los resultados en un diccionario por día.
    Al procesar cada día guarda un Parquet con los datos del día.
    Omite fechas ya procesadas (si existe el Parquet de salida).
    La iteración avanza día a día hasta alcanzar la fecha de parada.
    """
    # Fetch the web page
    borme_url = "https://www.boe.es/borme/dias"

    error_path = "/home/adri/scraper/scraper_BORME/errors"
    year = 2001
    month = 1
    day = 1

    path = '/home/adri/scraper/scraper_BORME/docs'

    actual_year = 2025
    actual_month = 3
    actual_day = 12

    finished = False

    while not finished:

        actual_borme_url = f"{borme_url}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}"

        response, response_find = try_pet(actual_borme_url, error_path)
        dict_id_txt = []
        
        id_txt = 1

        if response_find == 0:
            print(f"No se ha podido acceder a {actual_borme_url}")

        else:

            if os.path.exists(f"{path}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}/output.parquet"):
                print(f"Ya existe el archivo {path}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}/output.parquet")
            else:
                try:
                    if os.path.exists(f"{path}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}"):
                        os.rmdir(f"{path}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}/")
                except Exception as e:
                    print(f"Error al borrar el directorio: {e}")
                    pass

                if response.status_code == 200:

                    print(f"Accediendo a {actual_borme_url}")
                    # Parse the HTML content
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # Extract specific elements
                    option = soup.find("div", class_="sumario")

                    if option:
                        for link in option.find_all('a'):
                            if "pdf" in link.get('href'):
                                pdf_url = urllib.parse.urljoin(actual_borme_url, link.get('href'))
                                pdf_response, pdf_response_find = try_pet(pdf_url, error_path)
                                if pdf_response_find == 0:
                                    print(f"No se ha podido acceder a {pdf_url}")

                                else:
                                    if pdf_response.status_code == 200:

                                        print(f"Accediendo a {pdf_url}")

                                        pdf_path = f"{path}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}/"
                                        if not os.path.exists(pdf_path):
                                            os.makedirs(pdf_path)

                                        pdf_path += f"{link.get('href').split("/")[-1].split("-")[0]}.pdf"
                                        print(f"Guardando archivo en {pdf_path}")
                                        if os.path.exists(pdf_path):
                                            print(f"El archivo {pdf_path} ya existe")
                                            continue

                                        with open(pdf_path, "wb") as file:
                                            file.write(pdf_response.content)

                                        text = pdf_to_text(pdf_path)
                                        dict_id_txt.append({"id": id_txt, "text": text})
                                        id_txt += 1
                                    else:
                                        print(f"No se ha podido acceder a {pdf_url}")
                                        id_txt += 1
                    
                    if dict_id_txt:
                        df = pl.DataFrame(dict_id_txt)

                        df.write_parquet(f"{path}/{str(year)}/{str(month).zfill(2)}/{str(day).zfill(2)}/output.parquet")

                if response.status_code == 404:
                    print(f"No hay datos en {actual_borme_url}")

            day += 1
            if day > 31 and month in [1, 3, 5, 7, 8, 10, 12]:
                day = 1
                month += 1
            elif day > 30 and month in [4, 6, 9, 11]:
                day = 1
                month += 1
            elif day > 28 and month == 2:
                day = 1
                month += 1
            elif month > 12:
                year += 1
                month = 1
                day = 1
                
            if year == actual_year and month == actual_month and day == actual_day:
                finished = True
                
                        # else:
                        #     df = pl.DataFrame(dict_id_txt)

                        #     df.write_parquet(f"{path}/{org}/output.parquet")
                        #     finished = True

if __name__ == "__main__":
    main()