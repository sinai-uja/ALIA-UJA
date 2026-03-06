"""Recolector de jurisprudencia del Tribunal de Justicia de la UE (EUR-Lex).

Este script automatiza la descarga múltiple de resoluciones del Tribunal de Justicia desde
el portal EUR-Lex. Itera sobre las páginas de resultados de la búsqueda avanzada, extrae
enlsáces a documentos y descarga cada PDF en los idiomas configurados (ES, EN, DE, FR, IT, PT).
Extrae el texto con PyMuPDF y genera un archivo Parquet único con todos los resultados.

Attributes:
    ids_lenguage (list[str]): Idiomas a descargar para cada documento.
    max_pages (int): Número máximo de páginas de resultados a procesar.
    path (str): Directorio local donde se almacenan los PDFs y el Parquet de salida.
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
    """Orquestador del scraping de EUR-Lex (Tribunal de Justicia de la UE).

    Itera sobre las páginas de búsqueda de EUR-Lex con los filtros del Tribunal de Justicia (CJ).
    Por cada documento encontrado construye las URLs de descarga en cada idioma configurado,
    descarga los PDFs, extrae el texto con PyMuPDF y lo acumula en un diccionario por idioma.
    Al finalizar genera un Parquet único con todos los textos.
    URLs de documentos 404 (no disponibles en ese idioma) se registran en un log específico.
    """
    # Fetch the web page
    eurlex_url = "https://eur-lex.europa.eu/search.html?orAU_CODEDGroup=AU_CODED%3DCJ&sortOneOrder=desc&sortOne=TI_SORT&page="
    download_url = 'https://eur-lex.europa.eu/legal-content'
    
    error_path = "/home/adri/scraper/scraper_EURLEX/errors"
    error_page_path = "/home/adri/scraper/scraper_EURLEX/errors_page"
    actual_page = 1
    path = '/home/adri/scraper/scraper_EURLEX/docs'
    no_lenguage_file = '/home/adri/scraper/scraper_EURLEX/docs'
    ids_lenguage = ["ES", "EN", "DE", "FR", "IT", "PT"]
    max_pages = 7816
    dict_id_txt = {}

    for lenguage in ids_lenguage:
        dict_id_txt[lenguage] = []

    id_txt = 1
    finished = False

    while not finished:

        actual_eurlex_url = f"{eurlex_url}{actual_page}&lang=es&type=advanced&qid=1741774396292"
        response, response_find = try_pet(actual_eurlex_url, error_path)
        
        if response_find == 0:
            print(f"No se ha podido acceder a {actual_eurlex_url}")

        else:

            if os.path.exists(f"{path}/output.parquet"):
                print(f"Ya existe el archivo {path}/output.parquet")
                sys.exit()
            else:
                if response.status_code == 200:

                    print(f"Accediendo a página {actual_eurlex_url}")
                    # Parse the HTML content
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # Extract specific elements
                    try:
                        options = soup.find("div", class_="EurlexContent RelocateFilteringWidget")

                        for option in options.find_all("ul", class_="SearchResultDoc"):
                            link = option.find("a")['href'].split('?uri=')[-1]

                            for lenguage in ids_lenguage:
                                link = link.replace("EN", lenguage)
                                pdf_url = f"{download_url}/{lenguage}/TXT/PDF/?uri={link}"
                                print(f"Accediendo a {pdf_url}")
                                pdf_response, pdf_response_find = try_pet(pdf_url, error_path)

                                if pdf_response_find == 0:
                                    print(f"No se ha podido acceder a {pdf_url}")
                                else:
                                    if not os.path.exists(f"{path}/{lenguage}"):
                                        os.makedirs(f"{path}/{lenguage}")
                                    if pdf_response.status_code == 404:
                                        print(f"El documento {pdf_url} no está en español")
                                        try:
                                            with open(f"{no_lenguage_file}/{lenguage}_missign.txt", "a", encoding="utf-8") as file:
                                                file.write(pdf_url + "\n")
                                        except Exception as e:
                                            print(f"Error al escribir en el archivo de errores: {e}")
                                        continue
                                    if '/' in link:
                                        aux_link = link.split('?uri=')[-1]
                                        aux_link = aux_link.replace('/', "_")
                                        pdf_path = f"{path}/{lenguage}/{aux_link}.pdf"
                                    else:
                                        pdf_path = f"{path}/{lenguage}/{pdf_url.split('uri=')[-1]}.pdf"
                                    print(f"Guardando en {pdf_path}")

                                    with open(pdf_path, "wb") as file:
                                        file.write(pdf_response.content)
                                    
                                    try:
                                        text = pdf_to_text(pdf_path)
                                    except Exception as e:
                                        print(f"Error al convertir el PDF a texto: {e}")
                                        error_log(error_path, pdf_url)
                                        continue
                                    dict_id_txt[lenguage].append({"id": id_txt, "txt": text})
                            id_txt += 1
                    except Exception as e:
                        print(f"Error al extraer los elementos de la página {actual_page}: {e}")

                        continue

                    else:
                        print(f"No se han encontrado más documentos en la página {actual_page}")
                        print(f"Procesando página {actual_page} de {max_pages}")
                        actual_page += 1
                        continue
                else:
                    print(f"Error al acceder a la página {actual_page}")
                    error_log(error_page_path, pdf_url)
                    continue

        if actual_page == max_pages:
            finished = True
    
    df = pl.DataFrame(dict_id_txt)
    df.write_parquet(f"{path}/output.parquet")

if __name__ == "__main__":
    main()